"""Download every Fomo trade of the last N days from the chain into a SQLite file (resumable).

  python scripts/fomo_download.py <days> <out.db> [until_days_ago]

Trades are parsed like the live watcher (rhscanner.fomo.parse_fomo_logs); block times are interpolated
from block headers sampled every SAMPLE_BLOCKS. Archived with scripts/data_export.py.
"""

import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.config import USDG  # noqa: E402
from rhscanner.fomo import FOMO_ENTRY, FOMO_EXECUTOR, FOMO_TRANSFER_TOPIC, parse_fomo_logs  # noqa: E402

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TO_EXECUTOR = "0x" + "0" * 24 + FOMO_EXECUTOR[2:]

URLS = ["https://rpc.mainnet.chain.robinhood.com", "https://robinhood.drpc.org"]
DAY_BLOCKS = 864_000
SAMPLE_BLOCKS = 20_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (block INTEGER, ts REAL, token INTEGER, side INTEGER, trader INTEGER,
                                   usd REAL, amount REAL);
CREATE TABLE IF NOT EXISTS names (id INTEGER PRIMARY KEY, kind TEXT, addr TEXT, UNIQUE (kind, addr));
CREATE TABLE IF NOT EXISTS blocks (block INTEGER PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT);
"""


def call(method, params, attempts=8):
    for i in range(attempts):
        url = URLS[i % len(URLS)]
        try:
            req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                          "params": params}).encode(),
                                         {"content-type": "application/json", "user-agent": "curl/8.0"})
            res = json.load(urllib.request.urlopen(req, timeout=120))
            if "error" in res:
                msg = res["error"].get("message", "")
                if "exceeds limit" in msg:
                    raise OverflowError(msg)
                raise RuntimeError(msg)
            return res["result"]
        except OverflowError:
            raise
        except Exception as exc:
            print(f"retry {method} ({exc})", flush=True)
            time.sleep(min(60, 2 ** i))
    raise RuntimeError(f"{method} failed")


def block_ts(db, block):
    row = db.execute("SELECT ts FROM blocks WHERE block = ?", (block,)).fetchone()
    if row:
        return row[0]
    ts = int(call("eth_getBlockByNumber", [hex(block), False])["timestamp"], 16)
    db.execute("INSERT OR IGNORE INTO blocks VALUES (?, ?)", (block, ts))
    return ts


def main():
    days, out = float(sys.argv[1]), sys.argv[2]
    db = sqlite3.connect(out)
    db.executescript(SCHEMA)
    ids = {(k, a): i for i, k, a in db.execute("SELECT id, kind, addr FROM names")}

    def name(kind, addr):
        key = (kind, addr.lower())
        if key not in ids:
            cur = db.execute("INSERT INTO names (kind, addr) VALUES (?, ?)", key)
            ids[key] = cur.lastrowid
        return ids[key]

    head = int(call("eth_blockNumber", []), 16)
    state = dict(db.execute("SELECT k, v FROM state"))
    start = int(state.get("start", head - int(days * DAY_BLOCKS)))
    until = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    end = int(state.get("end", head - int(until * DAY_BLOCKS)))
    done = int(state.get("done", start))
    db.execute("INSERT OR REPLACE INTO state VALUES ('start', ?), ('end', ?)", (str(start), str(end)))
    step, t0 = 8000, time.time()
    while done < end:
        to = min(done + step, end)
        try:
            logs = call("eth_getLogs", [{"fromBlock": hex(done), "toBlock": hex(to - 1),
                                         "address": [FOMO_ENTRY, FOMO_EXECUTOR], "topics": [FOMO_TRANSFER_TOPIC]}])
        except OverflowError:
            step = max(500, step // 2)
            continue
        # Fomo's own events carry no dollar amount for sells: the USDG the DEX pays the executor does
        try:
            paid = call("eth_getLogs", [{"fromBlock": hex(done), "toBlock": hex(to - 1), "address": USDG,
                                         "topics": [TRANSFER, None, TO_EXECUTOR]}])
        except OverflowError:
            step = max(500, step // 2)
            continue
        usdg_in: dict[str, float] = {}
        for entry in paid:
            usdg_in[entry["transactionHash"]] = max(usdg_in.get(entry["transactionHash"], 0),
                                                    int(entry["data"], 16) / 1e6)
        lo = (done // SAMPLE_BLOCKS) * SAMPLE_BLOCKS
        hi = lo + SAMPLE_BLOCKS
        t_lo, t_hi = block_ts(db, lo), block_ts(db, hi) if hi <= head else block_ts(db, head)
        span = (hi if hi <= head else head) - lo
        rows = []
        for t in parse_fomo_logs(logs):
            ts = t_lo + (t.block - lo) * (t_hi - t_lo) / span if span else t_lo
            usd = t.usd if t.side == "buy" else usdg_in.get(t.tx_hash)
            rows.append((t.block, ts, name("token", t.token), 1 if t.side == "buy" else 0, name("trader", t.trader),
                         usd, float(t.amount)))
        db.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        done = to
        db.execute("INSERT OR REPLACE INTO state VALUES ('done', ?)", (str(done),))
        db.commit()
        if len(logs) < 4000 and step < 16000:
            step = int(step * 1.25)
        pct = 100 * (done - start) / (end - start)
        print(f"{pct:5.1f}% blok {done} · {len(rows)} işlem · {time.time() - t0:.0f} sn", flush=True)
    db.execute("CREATE INDEX IF NOT EXISTS trades_token ON trades (token, ts)")
    db.commit()
    print("bitti", db.execute("SELECT COUNT(*) FROM trades").fetchone()[0], "işlem", flush=True)


if __name__ == "__main__":
    main()
