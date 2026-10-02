"""Rebuild a trades DB (the scripts/fomo_download.py format) from the parquet files of the `veri` branch.

  git fetch origin veri && git worktree add /tmp/veri origin/veri
  python scripts/data_import.py /tmp/veri <trades.db>
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fomo_download import SCHEMA  # noqa: E402


def main():
    src, db = Path(sys.argv[1]), sqlite3.connect(sys.argv[2])
    db.executescript(SCHEMA)
    db.execute("CREATE TABLE IF NOT EXISTS supply (addr TEXT PRIMARY KEY, raw REAL)")
    ids: dict[tuple[str, str], int] = {}

    def name_ids(kind, values):
        new = [v for v in pd.unique(values) if (kind, v) not in ids]
        for v in new:
            ids[(kind, v)] = db.execute("INSERT INTO names (kind, addr) VALUES (?, ?)", (kind, v)).lastrowid
        return values.map(lambda v: ids[(kind, v)])

    for path in sorted(src.glob("trades_*.parquet")):
        df = pd.read_parquet(path)
        df["token"] = name_ids("token", df["token"].astype(str))
        df["trader"] = name_ids("trader", df["trader"].astype(str))
        db.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)",
                       df[["block", "ts", "token", "side", "trader", "usd", "amount"]].itertuples(index=False))
        db.commit()
        print(path.name, len(df), flush=True)
    if (src / "supply.parquet").exists():
        sup = pd.read_parquet(src / "supply.parquet")
        db.executemany("INSERT OR REPLACE INTO supply VALUES (?, ?)", sup.itertuples(index=False))
    db.execute("CREATE INDEX IF NOT EXISTS trades_token ON trades (token, ts)")
    db.commit()
    print("bitti", db.execute("SELECT COUNT(*) FROM trades").fetchone()[0], flush=True)


if __name__ == "__main__":
    main()
