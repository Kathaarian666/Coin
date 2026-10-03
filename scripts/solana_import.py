"""Load the pump.fun data from the `veri` branch (rhscanner/solana_export.py) into a SQLite research database.

  python scripts/solana_import.py <veri folder> <db>

Same tables as the collector (rhscanner/solana.py SCHEMA), filled by column name (older days have fewer columns);
days already in the database are skipped; pools and mints are the latest snapshots.
"""

import csv
import gzip
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.solana import SCHEMA  # noqa: E402

NUM = {"slot", "ts", "venue", "side", "lamports", "tokens", "vsol", "vtok", "rsol", "rtok", "minute", "total", "curve",
       "pumpswap", "other", "usd", "first_seen", "created_ts", "older_than", "complete_ts", "curve"}


def read(path: Path) -> tuple[list[str], list[list]]:
    with gzip.open(path, "rt", newline="") as f:
        r = csv.reader(f)
        head = next(r)
        return head, [[None if v == "" else (float(v) if h in NUM else v) for h, v in zip(head, row)] for row in r]


def put(db, table: str, path: Path, verb: str = "INSERT"):
    """Rows by column name (older files have fewer columns)."""
    head, data = read(path)
    db.executemany(f"{verb} INTO {table} ({', '.join(head)}) VALUES ({', '.join('?' * len(head))})", data)
    return len(data)


def main():
    src, db = Path(sys.argv[1]) / "solana", sqlite3.connect(sys.argv[2])
    db.executescript(SCHEMA + "CREATE TABLE IF NOT EXISTS imported (day TEXT PRIMARY KEY);")
    done = {d for (d,) in db.execute("SELECT day FROM imported")}
    for day in sorted(p.name for p in src.iterdir() if p.is_dir()):
        if day in done:
            continue
        n = sum(put(db, "trades", part) for part in sorted((src / day).glob("trades_*.csv.gz")))
        put(db, "stats", src / day / "stats.csv.gz", "INSERT OR REPLACE")
        put(db, "sol_price", src / day / "sol_price.csv.gz", "INSERT OR REPLACE")
        db.execute("INSERT INTO imported VALUES (?)", (day,))
        db.commit()
        print(f"{day}: {n} işlem")
    for table in ("pools", "mints"):
        if (src / f"{table}.csv.gz").exists():
            put(db, table, src / f"{table}.csv.gz", "INSERT OR REPLACE")
    db.commit()


if __name__ == "__main__":
    main()
