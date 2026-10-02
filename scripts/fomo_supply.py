"""Fetch totalSupply (raw units) of every coin in a trades DB (scripts/fomo_download.py) into its `supply` table.

  python scripts/fomo_supply.py <trades.db>

FDV = price (USD per raw unit) x raw supply, whatever the decimals.
"""

import json
import sqlite3
import sys
import time
import urllib.request

URL = "https://rpc.mainnet.chain.robinhood.com"
TOTAL_SUPPLY = "0x18160ddd"


def batch(calls):
    body = [{"jsonrpc": "2.0", "id": i, "method": "eth_call", "params": [{"to": a, "data": TOTAL_SUPPLY}, "latest"]}
            for i, a in enumerate(calls)]
    for attempt in range(8):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(),
                                         {"content-type": "application/json", "user-agent": "curl/8.0"})
            res = json.load(urllib.request.urlopen(req, timeout=120))
            return {r["id"]: r.get("result") for r in res}
        except Exception as exc:
            print("retry", exc, flush=True)
            time.sleep(2 ** attempt)
    return {}


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
            value = res.get(i)
            rows.append((addr, float(int(value, 16)) if value and value != "0x" else None))
        db.executemany("INSERT OR REPLACE INTO supply VALUES (?, ?)", rows)
        db.commit()
        if k % 1000 == 0:
            print(f"{k}/{len(todo)}", flush=True)
    print("bitti", db.execute("SELECT COUNT(*), COUNT(raw) FROM supply").fetchone(), flush=True)


if __name__ == "__main__":
    main()
