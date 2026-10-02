"""Append the trades of one trades DB (scripts/fomo_download.py) to another, mapping coin and wallet ids.

  python scripts/data_merge.py <from.db> <into.db>

Only blocks after the last block already in <into.db> are copied, so running it twice changes nothing.
"""

import sqlite3
import sys


def main():
    src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
    last = dst.execute("SELECT COALESCE(MAX(block), 0) FROM trades").fetchone()[0]
    ids = {(k, a): i for i, k, a in dst.execute("SELECT id, kind, addr FROM names")}
    src_names = {i: (k, a) for i, k, a in src.execute("SELECT id, kind, addr FROM names")}

    def map_id(i):
        key = src_names[i]
        if key not in ids:
            ids[key] = dst.execute("INSERT INTO names (kind, addr) VALUES (?, ?)", key).lastrowid
        return ids[key]

    rows = [(b, ts, map_id(tok), side, map_id(trd), usd, amt) for b, ts, tok, side, trd, usd, amt in
            src.execute("SELECT block, ts, token, side, trader, usd, amount FROM trades WHERE block > ?", (last,))]
    dst.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    dst.commit()
    print(f"{len(rows):,} işlem eklendi (blok > {last}); son blok",
          dst.execute("SELECT MAX(block) FROM trades").fetchone()[0])


if __name__ == "__main__":
    main()
