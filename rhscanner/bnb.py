"""BNB Chain collector (PROJE.md §4.5b, step 6): every Fomo trade leg and every flap.sh launch, live, into SQLite.

  python -m rhscanner.bnb [<db>=bnb.db]

Fomo runs the same two contracts on BNB as on Robinhood Chain (entry / executor, same event), so the Robinhood
parser applies (rhscanner/fomo.py; cash here is USDC 0x8ac76a51... with 18 decimals, and BNB). Free BNB RPCs keep
logs for about an hour only, so there is no history to download: this polls the newest blocks every few seconds.
Tables (amounts REAL, raw units; ts = block time, interpolated between the polled head blocks):
- fomo(block, ts, tx, li, emitter, src, dst, token, amount): the Fomo event legs (entry: user -> executor,
  executor: executor -> user)
- usdc_in(block, ts, tx, li, src, amount): USDC transfers to the executor (a sell's dollar size, as on Robinhood)
- launches(token, block, ts, creator, name, symbol): flap.sh TokenCreated (portal 0xe2ce6ab8...; most Fomo coins on
  BNB end in ...7777), the launch index like Pons on Robinhood
- heads(block, ts): the polled head blocks
"""

import asyncio
import logging
import sqlite3
import sys
import time

import httpx

log = logging.getLogger(__name__)

URL = "https://bsc-rpc.publicnode.com"  # getLogs needs an address filter; ~1 h of logs
FOMO_ENTRY = "0xccc88a9d1b4ed6b0eaba998850414b24f1c315be"
FOMO_EXECUTOR = "0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f"
FOMO_TOPIC = "0xafbab204e8271965231d37baed9b1abca8725b7409c70314455f68bc89142b91"
USDC = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
FLAP_PORTAL = "0xe2ce6ab80874fa9fa2aae65d277dd6b8e65c9de0"
# TokenCreated(uint256 ts, address creator, uint256 nonce, address token, string name, string symbol, string meta)
FLAP_CREATED = "0x504e7f360b2e5fe33cbaaae4c593bc55305328341bf79009e43e0e3b7f699603"
POLL = 4.0  # s
MAX_RANGE = 400  # blocks per query (~3 min)
START_BACK = 100  # blocks before the head on a fresh start

SCHEMA = """CREATE TABLE IF NOT EXISTS fomo (block INTEGER, ts REAL, tx TEXT, li INTEGER, emitter TEXT, src TEXT,
            dst TEXT, token TEXT, amount REAL, PRIMARY KEY (tx, li));
            CREATE INDEX IF NOT EXISTS fomo_token ON fomo (token, block);
            CREATE TABLE IF NOT EXISTS usdc_in (block INTEGER, ts REAL, tx TEXT, li INTEGER, src TEXT, amount REAL,
                                                PRIMARY KEY (tx, li));
            CREATE TABLE IF NOT EXISTS launches (token TEXT PRIMARY KEY, block INTEGER, ts REAL, creator TEXT,
                                                 name TEXT, symbol TEXT);
            CREATE TABLE IF NOT EXISTS heads (block INTEGER PRIMARY KEY, ts INTEGER);
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value INTEGER);"""


def _words(data: str) -> list[str]:
    d = data[2:]
    return [d[i:i + 64] for i in range(0, len(d), 64)]


def _addr(word: str) -> str:
    return "0x" + word[-40:]


def _string(words: list[str], offset_word: str) -> str:
    """An ABI string inside the event data (offset in bytes from the data start)."""
    try:
        i = int(offset_word, 16) // 32
        n = int(words[i], 16)
        return bytes.fromhex("".join(words[i + 1: i + 1 + (n + 31) // 32]))[:n].decode("utf-8", "replace")
    except (ValueError, IndexError):
        return ""


def parse_fomo(e: dict) -> tuple | None:
    w = _words(e["data"])
    if len(w) < 4:
        return None
    return (e["address"].lower(), _addr(w[0]), _addr(w[1]), _addr(w[2]), float(int(w[3], 16)))


def parse_launch(e: dict) -> tuple | None:
    w = _words(e["data"])
    if len(w) < 7:
        return None
    return (_addr(w[3]), _addr(w[1]), _string(w, w[4]), _string(w, w[5]))


class Collector:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, timeout=60)
        self.db.executescript(SCHEMA)
        self.http = httpx.AsyncClient(timeout=30, headers={"user-agent": "curl/8.0"})
        row = self.db.execute("SELECT block, ts FROM heads ORDER BY block DESC LIMIT 1").fetchone()
        self.prev = row  # (block, ts) of the last polled head
        done = self.db.execute("SELECT value FROM state WHERE key = 'done'").fetchone()
        self.done = done[0] if done else None

    async def rpc(self, method: str, params: list):
        for attempt in range(6):
            try:
                r = await self.http.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if r.status_code in (403, 429, 502, 503):
                    raise RuntimeError(f"HTTP {r.status_code}")
                res = r.json()
                if "error" in res:
                    raise RuntimeError(str(res["error"])[:200])
                return res["result"]
            except (RuntimeError, httpx.HTTPError, ValueError) as exc:
                if attempt == 5:
                    raise
                log.debug("%s retry: %s", method, exc)
                await asyncio.sleep(3 * (attempt + 1))

    def ts_of(self, block: int, head: tuple) -> float:
        """Block time between the previous and this polled head (linear), else 0.45 s blocks from this head."""
        hb, ht = head
        if self.prev and self.prev[0] < hb:
            pb, pt = self.prev
            return pt + (block - pb) * (ht - pt) / (hb - pb)
        return ht - (hb - block) * 0.45

    async def step(self):
        head_block = await self.rpc("eth_getBlockByNumber", ["latest", False])
        hb, ht = int(head_block["number"], 16), int(head_block["timestamp"], 16)
        lo = (self.done + 1) if self.done is not None else hb - START_BACK
        if hb - lo > 6000:  # down for a while: the free node only keeps ~1 h; take what is still there
            log.warning("%d blocks behind; skipping to the last 6000", hb - lo)
            lo = hb - 6000
        while lo <= hb:
            hi = min(hb, lo + MAX_RANGE - 1)
            fomo = await self.rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi),
                                                   "address": [FOMO_ENTRY, FOMO_EXECUTOR], "topics": [FOMO_TOPIC]}])
            usdc = await self.rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "address": USDC,
                                                   "topics": [TRANSFER, None, "0x" + "0" * 24 + FOMO_EXECUTOR[2:]]}])
            made = await self.rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "address": FLAP_PORTAL,
                                                   "topics": [FLAP_CREATED]}])
            rows_f, rows_u, rows_l = [], [], []
            for e in fomo:
                p = parse_fomo(e)
                if p:
                    b = int(e["blockNumber"], 16)
                    rows_f.append((b, self.ts_of(b, (hb, ht)), e["transactionHash"], int(e["logIndex"], 16), *p))
            for e in usdc:
                b = int(e["blockNumber"], 16)
                rows_u.append((b, self.ts_of(b, (hb, ht)), e["transactionHash"], int(e["logIndex"], 16),
                               _addr(e["topics"][1]), float(int(e["data"], 16))))
            for e in made:
                p = parse_launch(e)
                if p:
                    b = int(e["blockNumber"], 16)
                    rows_l.append((p[0], b, self.ts_of(b, (hb, ht)), *p[1:]))
            self.db.executemany("INSERT OR IGNORE INTO fomo VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows_f)
            self.db.executemany("INSERT OR IGNORE INTO usdc_in VALUES (?, ?, ?, ?, ?, ?)", rows_u)
            self.db.executemany("INSERT OR IGNORE INTO launches VALUES (?, ?, ?, ?, ?, ?)", rows_l)
            self.done = hi
            self.db.execute("INSERT OR REPLACE INTO state VALUES ('done', ?)", (hi,))
            self.db.commit()
            lo = hi + 1
        self.db.execute("INSERT OR REPLACE INTO heads VALUES (?, ?)", (hb, ht))
        self.db.commit()
        self.prev = (hb, ht)

    async def run(self):
        last_log = 0.0
        while True:
            try:
                await self.step()
                if time.time() - last_log >= 60:
                    n = self.db.execute("SELECT COUNT(DISTINCT tx) FROM fomo WHERE ts >= ?", (time.time() - 60,)).fetchone()[0]
                    k = self.db.execute("SELECT COUNT(*) FROM launches WHERE ts >= ?", (time.time() - 60,)).fetchone()[0]
                    log.info("last minute: %d Fomo trades, %d flap.sh launches (block %s)", n, k, self.done)
                    last_log = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("poll failed (%s); trying again", exc)
                await asyncio.sleep(10)
            await asyncio.sleep(POLL)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(Collector(sys.argv[1] if len(sys.argv) > 1 else "bnb.db").run())


if __name__ == "__main__":
    main()
