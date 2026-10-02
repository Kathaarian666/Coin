"""Fetch totalSupply (raw units) of every coin in a trades DB (scripts/fomo_download.py) into its `supply` table.

  python scripts/fomo_supply.py <trades.db>

FDV = price (USD per raw unit) x raw supply, whatever the decimals.
"""

import json
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URLS = ["https://robinhood.drpc.org", "https://rpc.mainnet.chain.robinhood.com"]  # dRPC first: the public node is busy with log downloads
TOTAL_SUPPLY = "0x18160ddd"


def one(addr):
    """totalSupply over dRPC (its free tier refuses batched eth_calls, the public node is busy with log downloads)."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": addr, "data": TOTAL_SUPPLY}, "latest"]}
    for attempt in range(6):
        try:
            req = urllib.request.Request(URLS[attempt % 2], json.dumps(body).encode(),
                                         {"content-type": "application/json", "user-agent": "curl/8.0"})
            res = json.load(urllib.request.urlopen(req, timeout=60))
            if "error" in res and "revert" not in str(res["error"]).lower():
                raise RuntimeError(res["error"])
            return res.get("result") or "0x"
        except Exception as exc:
            print("retry", exc, flush=True)
            time.sleep(2 ** attempt)
    return None  # refused: not stored, asked again on the next run


def batch(calls):
    with ThreadPoolExecutor(8) as pool:
        return {i: v for i, v in enumerate(pool.map(one, calls)) if v is not None}


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)  # other scripts may use the DB meanwhile
    db.execute("CREATE TABLE IF NOT EXISTS supply (addr TEXT PRIMARY KEY, raw REAL)")
    have = {a for (a,) in db.execute("SELECT addr FROM supply")}
    # every coin that reaches an alert moment (3 distinct buyers). Not "20 trades in total": whether a coin trades on
    # is future knowledge, and a missing FDV would then tell the model the coin dies (found 2 Oct)
    todo = [a for (a,) in db.execute(
        "SELECT n.addr FROM names n JOIN (SELECT token, COUNT(DISTINCT trader) c FROM trades WHERE side = 1 "
        "GROUP BY token) t ON t.token = n.id WHERE n.kind = 'token' AND t.c >= 3") if a not in have]
    for k in range(0, len(todo), 50):
        chunk = todo[k:k + 50]
        res = batch(chunk)
        rows = []
        for i, addr in enumerate(chunk):
            if i not in res:
                continue  # refused: not stored, asked again on the next run
            value = res[i]
            rows.append((addr, float(int(value, 16)) if value and value != "0x" else None))
        db.executemany("INSERT OR REPLACE INTO supply VALUES (?, ?)", rows)
        db.commit()
        if k % 1000 == 0:
            print(f"{k}/{len(todo)}", flush=True)
    print("bitti", db.execute("SELECT COUNT(*), COUNT(raw) FROM supply").fetchone(), flush=True)


if __name__ == "__main__":
    main()
