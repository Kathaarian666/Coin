"""Download every Pons V2 launch (token, curve, launcher) over a trades DB's span (plus earlier days) into it.

  python scripts/pons_launches.py <trades.db> [<days before the first trade>=14] [--all]

Table `launches(token, curve, launcher, block, ts)`; ts is interpolated from the trades' block times.
Continues after the last launch already in the table (new days); --all downloads the whole span again.
"""

import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.checks.deployer import PONS_V2_FACTORY, PONS_V2_LAUNCH  # noqa: E402

URL = "https://rpc.mainnet.chain.robinhood.com"
STEP = 300_000
BLOCKS_PER_DAY = 864_000


def get_logs(lo, hi):
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs",
            "params": [{"fromBlock": hex(lo), "toBlock": hex(hi), "address": PONS_V2_FACTORY, "topics": [PONS_V2_LAUNCH]}]}
    for attempt in range(8):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(),
                                         {"content-type": "application/json", "user-agent": "curl/8.0"})
            res = json.load(urllib.request.urlopen(req, timeout=120))
            if "error" in res:
                raise RuntimeError(res["error"])
            return res["result"]
        except Exception as exc:
            if "exceeds" in str(exc) or "limit" in str(exc):
                mid = (lo + hi) // 2
                return get_logs(lo, mid) + get_logs(mid + 1, hi)
            print("retry", exc, flush=True)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{lo}-{hi} failed")


def main():
    db = sqlite3.connect(sys.argv[1])
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    before = float(args[0]) if args else 14
    db.execute("CREATE TABLE IF NOT EXISTS launches (token TEXT PRIMARY KEY, curve TEXT, launcher TEXT, block INTEGER, ts REAL)")
    sample = np.array(db.execute("SELECT block, ts FROM trades WHERE rowid % 500 = 0 ORDER BY block").fetchall(), float)
    lo, hi = int(sample[0, 0] - before * BLOCKS_PER_DAY), int(sample[-1, 0])
    rate = np.polyfit(sample[:, 0], sample[:, 1], 1)
    last = db.execute("SELECT MAX(block) FROM launches").fetchone()[0]
    if last and "--all" not in sys.argv:
        lo = max(lo, last - 1000)
    t0 = time.time()
    for start in range(lo, hi + 1, STEP):
        rows = []
        for e in get_logs(start, min(hi, start + STEP - 1)):
            block = int(e["blockNumber"], 16)
            ts = float(np.interp(block, sample[:, 0], sample[:, 1], left=np.nan, right=np.nan))
            if np.isnan(ts):
                ts = float(np.polyval(rate, block))
            topic = lambda k: "0x" + e["topics"][k][-40:]  # noqa: E731
            rows.append((topic(1), topic(2), topic(3), block, ts))
        db.executemany("INSERT OR REPLACE INTO launches VALUES (?, ?, ?, ?, ?)", rows)
        db.commit()
        if (start - lo) // STEP % 20 == 0:
            print(f"{(start - lo) / (hi - lo):.0%} · {db.execute('SELECT COUNT(*) FROM launches').fetchone()[0]} lansman "
                  f"· {time.time() - t0:.0f} sn", flush=True)
    print("bitti", db.execute("SELECT COUNT(*), COUNT(DISTINCT launcher) FROM launches").fetchone(), flush=True)


if __name__ == "__main__":
    main()
