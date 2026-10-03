"""Load the pump.fun data from the `veri` branch (rhscanner/solana_export.py) into a SQLite research database.

  python scripts/solana_import.py <veri folder> <db>

Same tables as the collector (rhscanner/solana.py SCHEMA); days already in the database are skipped.
"""

import csv
import gzip
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.solana import SCHEMA  # noqa: E402

NUM = {"slot", "ts", "venue", "side", "lamports", "tokens", "vsol", "vtok", "minute", "total", "curve", "pumpswap",
       "other", "usd"}


def rows(path: Path):
    with gzip.open(path, "rt", newline="") as f:
        r = csv.reader(f)
        head = next(r)
        for row in r:
            yield [None if v == "" else (float(v) if h in NUM else v) for h, v in zip(head, row)]


def main():
    src, db = Path(sys.argv[1]) / "solana", sqlite3.connect(sys.argv[2])
    db.executescript(SCHEMA + "CREATE TABLE IF NOT EXISTS imported (day TEXT PRIMARY KEY);")
    done = {d for (d,) in db.execute("SELECT day FROM imported")}
    for day in sorted(p.name for p in src.iterdir() if p.is_dir()):
        if day in done:
            continue
        n = 0
        for part in sorted((src / day).glob("trades_*.csv.gz")):
            batch = list(rows(part))
            db.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
            n += len(batch)
        db.executemany("INSERT OR REPLACE INTO stats VALUES (?, ?, ?, ?, ?)", rows(src / day / "stats.csv.gz"))
        db.executemany("INSERT OR REPLACE INTO sol_price VALUES (?, ?)", rows(src / day / "sol_price.csv.gz"))
        db.execute("INSERT INTO imported VALUES (?)", (day,))
        db.commit()
        print(f"{day}: {n} işlem")
    if (src / "pools.csv.gz").exists():
        db.executemany("INSERT OR REPLACE INTO pools VALUES (?, ?, ?)", rows(src / "pools.csv.gz"))
        db.commit()


if __name__ == "__main__":
    main()
