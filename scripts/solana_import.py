"""Load the pump.fun data from the `veri` branch (rhscanner/solana_export.py) into a SQLite research database.

  python scripts/solana_import.py <veri folder> <db>
  python scripts/solana_import.py <veri folder> <db> --chain bnb       BNB Chain (rhscanner/bnb.py tables)
  python scripts/solana_import.py <veri folder> <fomo.db> --chain robinhood
        Robinhood days the bot saw (robinhood/<day>/trades.csv.gz) into the research trades DB (fomo_download.py
        format, names ids); only blocks after its last one, like scripts/data_merge.py

Same tables as the collector (rhscanner/solana.py SCHEMA), filled by column name (older days have fewer columns);
days already in the database are skipped; pools and mints are the latest snapshots.
"""

import csv
import gzip
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner import bnb, solana  # noqa: E402

NUM = {"slot", "ts", "venue", "side", "lamports", "tokens", "vsol", "vtok", "rsol", "rtok", "minute", "total", "curve",
       "pumpswap", "other", "usd", "first_seen", "created_ts", "older_than", "complete_ts", "curve", "block", "li", "amount"}  # (robinhood columns are converted in import_robinhood)


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


def import_robinhood(src: Path, db: sqlite3.Connection):
    from fomo_download import SCHEMA as RH_SCHEMA
    db.executescript(RH_SCHEMA)
    ids = {(k, a): i for i, k, a in db.execute("SELECT id, kind, addr FROM names")}
    by_lower = {(k, a.lower()): i for (k, a), i in ids.items()}

    def name_id(kind, addr):
        key = (kind, addr.lower())
        if key not in by_lower:
            by_lower[key] = db.execute("INSERT INTO names (kind, addr) VALUES (?, ?)", (kind, addr)).lastrowid
        return by_lower[key]
    for day in sorted(p.name for p in src.iterdir() if p.is_dir()):
        last = db.execute("SELECT COALESCE(MAX(block), 0) FROM trades").fetchone()[0]
        head, rows = read(src / day / "trades.csv.gz")
        col = {h: i for i, h in enumerate(head)}
        new = [(int(r[col["block"]]), r[col["ts"]], name_id("token", r[col["token"]]), int(r[col["side"]]),
                name_id("trader", r[col["trader"]]), r[col["usd"]], float(r[col["amount"]]))
               for r in rows if int(r[col["block"]]) > last]
        db.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)", new)
        db.commit()
        print(f"{day}: {len(new)} işlem eklendi (blok > {last})")


def main():
    chain = sys.argv[sys.argv.index("--chain") + 1] if "--chain" in sys.argv else "solana"
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != chain]
    if chain == "robinhood":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        return import_robinhood(Path(args[0]) / "robinhood", sqlite3.connect(args[1], timeout=300))
    src, db = Path(args[0]) / chain, sqlite3.connect(args[1])
    db.executescript((bnb.SCHEMA if chain == "bnb" else solana.SCHEMA)
                     + "CREATE TABLE IF NOT EXISTS imported (day TEXT PRIMARY KEY);")
    done = {d for (d,) in db.execute("SELECT day FROM imported")}
    for day in sorted(p.name for p in src.iterdir() if p.is_dir()):
        if day in done:
            continue
        if chain == "bnb":
            n = sum(put(db, "fomo", part, "INSERT OR IGNORE") for part in sorted((src / day).glob("fomo_*.csv.gz")))
            put(db, "usdc_in", src / day / "usdc_in.csv.gz", "INSERT OR IGNORE")
            put(db, "launches", src / day / "launches.csv.gz", "INSERT OR REPLACE")
        else:
            n = sum(put(db, "trades", part) for part in sorted((src / day).glob("trades_*.csv.gz")))
            put(db, "stats", src / day / "stats.csv.gz", "INSERT OR REPLACE")
            put(db, "sol_price", src / day / "sol_price.csv.gz", "INSERT OR REPLACE")
        db.execute("INSERT INTO imported VALUES (?)", (day,))
        db.commit()
        print(f"{day}: {n} kayıt")
    for table in ("pools", "mints") if chain == "solana" else ():
        if (src / f"{table}.csv.gz").exists():
            put(db, table, src / f"{table}.csv.gz", "INSERT OR REPLACE")
    db.commit()


if __name__ == "__main__":
    main()
