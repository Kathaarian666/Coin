"""Save a trades DB (scripts/fomo_download.py) as one compressed parquet file per UTC day, for the `veri` branch.

  python scripts/data_export.py <trades.db> <out_dir>

A day already exported is merged with the new trades (duplicates dropped). Also writes supply.parquet.
Back: scripts/data_import.py.
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd


def main():
    db, out = sqlite3.connect(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    names = pd.read_sql("SELECT id, addr FROM names", db).set_index("id")["addr"]
    df = pd.read_sql("SELECT block, ts, token, side, trader, usd, amount FROM trades", db)
    df["token"] = df["token"].map(names).astype("category")
    df["trader"] = df["trader"].map(names).astype("category")
    df["side"] = df["side"].astype("int8")
    df["day"] = pd.to_datetime(df["ts"], unit="s").dt.strftime("%Y-%m-%d")
    for day, part in df.groupby("day"):
        path = out / f"trades_{day}.parquet"
        part = part.drop(columns="day")
        before = 0
        if path.exists():  # merge: another download may hold other hours of the same day
            old = pd.read_parquet(path)
            before = len(old)
            for col in ("token", "trader"):
                old[col], part[col] = old[col].astype(str), part[col].astype(str)
            part = pd.concat([old, part]).drop_duplicates(["block", "token", "trader", "side", "amount"])
            if len(part) == before:
                continue
        part = part.sort_values(["ts", "block"])
        for col in ("token", "trader"):
            part[col] = part[col].astype(str).astype("category")
        part.to_parquet(path, compression="zstd", index=False)
        print(f"{path.name}: {len(part)} işlem, {path.stat().st_size / 1e6:.1f} MB", flush=True)
    try:
        sup = pd.read_sql("SELECT addr, raw FROM supply", db)
        old = out / "supply.parquet"
        if old.exists():
            sup = pd.concat([pd.read_parquet(old), sup]).drop_duplicates("addr", keep="last")
        sup.to_parquet(old, compression="zstd", index=False)
    except Exception as exc:
        print("arz yok:", exc)


if __name__ == "__main__":
    main()
