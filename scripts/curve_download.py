"""Download the Pons bonding-curve trades (all buyers, from the launch) of the Pons coins in a winner_study table.

  python scripts/curve_download.py <trades.db> <winners.parquet> [<hours after launch>=6]

CurveBuy(router, buyer, eth, tokens, fee, tax) / CurveSell(router, seller, tokens, eth, fee, tax) from each coin's
curve contract (launches table). Table `curve_trades(token, block, li, side, trader, eth, tokens)` (eth, tokens in
whole units); done block ranges in `curve_ranges`. The curve stops trading when the coin graduates to a DEX pool.
"""

import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transfer_download import rpc  # noqa: E402

CURVE_BUY = "0xec36bf571f136799e8dc0b0b8bea4b04d8bd3d43de838aab0d5fc21d4cbfc455"
CURVE_SELL = "0x8113d738abdcb6b38357e9d53a54a7157861a09031b453651f0fe7fe151f59df"
STEP = 30_000


def logs(curve, lo, hi):
    try:
        return rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "address": curve,
                                    "topics": [[CURVE_BUY, CURVE_SELL]]}])
    except RuntimeError:
        if hi - lo < 10:
            raise
        mid = (lo + hi) // 2
        return logs(curve, lo, mid) + logs(curve, mid + 1, hi)


def main():
    """Chain-wide by block range (one query covers every curve; the node allows 30k blocks), kept for our coins."""
    db = sqlite3.connect(sys.argv[1])
    hours = float(sys.argv[3]) if len(sys.argv) > 3 else 6
    db.executescript("""CREATE TABLE IF NOT EXISTS curve_trades (token TEXT, block INTEGER, li INTEGER, side INTEGER,
                        trader TEXT, eth REAL, tokens REAL, PRIMARY KEY (token, block, li));
                        CREATE TABLE IF NOT EXISTS curve_ranges (lo INTEGER PRIMARY KEY);""")
    coins = set(pd.read_parquet(sys.argv[2], columns=["coin"]).coin)
    curves = {c.lower(): (t, b) for t, c, b in db.execute("SELECT lower(token), curve, block FROM launches") if t in coins}
    lo = min(b for _, b in curves.values())
    hi = max(b for _, b in curves.values()) + int(hours * 36000)
    done = {r for (r,) in db.execute("SELECT lo FROM curve_ranges")}
    starts = [x for x in range(lo, hi, STEP) if x not in done]
    t0 = time.time()

    def chain_logs(a, b):
        try:
            return rpc("eth_getLogs", [{"fromBlock": hex(a), "toBlock": hex(b), "topics": [[CURVE_BUY, CURVE_SELL]]}])
        except RuntimeError:
            if b - a < 10:
                raise
            mid = (a + b) // 2
            return chain_logs(a, mid) + chain_logs(mid + 1, b)

    def fetch(start):
        rows = []
        for e in chain_logs(start, start + STEP - 1):
            hit = curves.get(e["address"].lower())
            blk = int(e["blockNumber"], 16)
            if not hit or blk > hit[1] + hours * 36000:
                continue
            data, buy = e["data"], e["topics"][0].lower() == CURVE_BUY
            a, b = int(data[2:66], 16) / 1e18, int(data[66:130], 16) / 1e18
            eth, tokens = (a, b) if buy else (b, a)
            rows.append((hit[0], blk, int(e["logIndex"], 16), int(buy), "0x" + e["topics"][2][-40:], eth, tokens))
        return start, rows

    with ThreadPoolExecutor(4) as pool:
        for n, (start, rows) in enumerate(pool.map(fetch, starts)):
            db.executemany("INSERT OR IGNORE INTO curve_trades VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            db.execute("INSERT INTO curve_ranges VALUES (?)", (start,))
            db.commit()
            if n % 25 == 0:
                print(f"{n}/{len(starts)} aralık · {time.time() - t0:.0f} sn", flush=True)
    print("bitti", db.execute("SELECT COUNT(DISTINCT token), COUNT(*) FROM curve_trades").fetchone(),
          f"{time.time() - t0:.0f} sn", flush=True)


if __name__ == "__main__":
    main()
