"""Download the early ERC-20 Transfer logs of the coins in a winner_study table (all buyers, not only Fomo's).

  python scripts/transfer_download.py <trades.db> <winners.parquet> [<hours after first Fomo trade>=1] [<limit>]

Window: from the coin's Pons launch block (at most 1 h before its first Fomo trade) to N hours after its first
Fomo trade. Table `transfers(token, block, li, src, dst, value)`; done coins in `transfers_done`.
"""

import json
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

URL = "https://rpc.mainnet.chain.robinhood.com"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BLOCKS_PER_S = 10


def rpc(method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for attempt in range(8):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(),
                                         {"content-type": "application/json", "user-agent": "curl/8.0"})
            res = json.load(urllib.request.urlopen(req, timeout=120))
            if "error" in res:
                raise RuntimeError(res["error"])
            return res["result"]
        except Exception as exc:
            if "exceed" in str(exc) or "limit" in str(exc) or "range" in str(exc):
                raise
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError("rpc failed")


def logs(token, lo, hi):
    try:
        return rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "address": token, "topics": [TRANSFER]}])
    except RuntimeError:
        if hi - lo < 10:
            raise
        mid = (lo + hi) // 2
        return logs(token, lo, mid) + logs(token, mid + 1, hi)


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)  # other scripts may read the same DB meanwhile
    hours = float(sys.argv[3]) if len(sys.argv) > 3 else 1
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else None
    db.executescript("""CREATE TABLE IF NOT EXISTS transfers (token TEXT, block INTEGER, li INTEGER, src TEXT, dst TEXT,
                        value REAL, PRIMARY KEY (token, block, li));
                        CREATE TABLE IF NOT EXISTS transfers_done (token TEXT PRIMARY KEY);""")
    coins = pd.read_parquet(sys.argv[2], columns=["coin"]).coin.unique().tolist()
    done = {t for (t,) in db.execute("SELECT token FROM transfers_done")}
    launch = dict(db.execute("SELECT lower(token), block FROM launches"))
    first = dict(db.execute("SELECT lower(n.addr), MIN(t.block) FROM trades t JOIN names n ON n.id = t.token "
                            "GROUP BY t.token"))
    todo = [c for c in coins if c not in done][:limit]
    t0 = time.time()
    def fetch(coin):
        start = max(launch.get(coin) or 0, first[coin] - 3600 * BLOCKS_PER_S)
        end = first[coin] + int(hours * 3600 * BLOCKS_PER_S)
        return coin, [(coin, int(e["blockNumber"], 16), int(e["logIndex"], 16), "0x" + e["topics"][1][-40:],
                       "0x" + e["topics"][2][-40:], float(int(e["data"], 16)))
                      for e in logs(coin, start, end) if len(e["topics"]) == 3]

    with ThreadPoolExecutor(4) as pool:
        for n, (coin, rows) in enumerate(pool.map(fetch, todo)):
            db.executemany("INSERT OR IGNORE INTO transfers VALUES (?, ?, ?, ?, ?, ?)", rows)
            db.execute("INSERT INTO transfers_done VALUES (?)", (coin,))
            db.commit()
            if n % 250 == 0:
                print(f"{n}/{len(todo)} coin · {time.time() - t0:.0f} sn", flush=True)
    print("bitti", db.execute("SELECT COUNT(DISTINCT token), COUNT(*) FROM transfers").fetchone(), f"{time.time() - t0:.0f} sn")


if __name__ == "__main__":
    main()
