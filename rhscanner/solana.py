"""Solana collector (PROJE.md §4.5, step 6): every Fomo trade on pump.fun and PumpSwap, live, into SQLite.

  python -m rhscanner.solana [<db>=solana.db]

Fomo signs and pays gas for all of its Solana trades with one wallet (FEE_PAYER), so the public websocket's
logsSubscribe(mentions=[FEE_PAYER]) streams them all for free. The logs carry the venues' Anchor events:
- pump.fun bonding curve TradeEvent: mint, SOL, tokens, buy/sell, user, time, the curve's virtual reserves
- PumpSwap (graduated pump.fun coins) BuyEvent / SellEvent: time, base/quote amounts, pool, user; the pool's base
  mint is read once per pool (getAccountInfo) and cached
Other venues (Meteora, Raydium, ...) are counted but not stored yet. SOL/USD is sampled every 5 minutes.
Table trades(slot, ts, sig, venue 1 curve / 2 pumpswap, mint, side 1 buy / 0 sell, user, lamports, tokens,
vsol, vtok, pool, rsol, rtok); amounts are REAL (u64 can exceed SQLite's integers). Tokens are raw units (pump.fun
coins have 6 decimals), lamports = SOL * 1e9. Curve rows: vsol/vtok = the curve's virtual reserves (price), rsol/rtok =
its real reserves (rtok 0 = the curve is complete, the coin graduates). PumpSwap rows: vsol/vtok = the pool's
SOL / coin reserves after the trade (liquidity, price).
Table mints(mint, creator, first_seen, created_ts, older_than, complete_ts): the creator comes with every event;
created_ts = time of the coin's oldest transaction (its Create), looked up slowly in the background (the free RPC
limits getSignaturesForAddress); older_than = the oldest time seen when that search was cut short (MAX_PAGES);
complete_ts = the first trade seen with an empty curve; curve = 1 once the coin was seen on its bonding curve
(new coins: looked up first). Pools get created_ts / older_than the same way (a PumpSwap
pool is created when its coin graduates).
"""

import asyncio
import base64
import hashlib
import json
import logging
import sqlite3
import struct
import sys
import time

import httpx
import websockets

log = logging.getLogger(__name__)

FEE_PAYER = "AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51"
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
WS_URL = "wss://api.mainnet-beta.solana.com"
HTTP_URL = "https://api.mainnet-beta.solana.com"
SOL_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
TRADE_COLS = ("slot", "ts", "sig", "venue", "mint", "side", "user", "lamports", "tokens", "vsol", "vtok", "pool", "rsol",
              "rtok")
MAX_PAGES = 3  # getSignaturesForAddress pages (1000 each) searched for an account's oldest transaction
LOOKUP_GAP = 1.2  # s between those calls (the free RPC answers 429 when they come faster)


def _disc(name: str) -> bytes:
    return hashlib.sha256(f"event:{name}".encode()).digest()[:8]


TRADE, BUY, SELL = _disc("TradeEvent"), _disc("BuyEvent"), _disc("SellEvent")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

SCHEMA = """CREATE TABLE IF NOT EXISTS trades (slot INTEGER, ts INTEGER, sig TEXT, venue INTEGER, mint TEXT,
            side INTEGER, user TEXT, lamports REAL, tokens REAL, vsol REAL, vtok REAL, pool TEXT, rsol REAL, rtok REAL);
            CREATE INDEX IF NOT EXISTS trades_mint ON trades (mint, ts);
            CREATE TABLE IF NOT EXISTS pools (pool TEXT PRIMARY KEY, base TEXT, quote TEXT, created_ts INTEGER,
                                              older_than INTEGER);
            CREATE TABLE IF NOT EXISTS mints (mint TEXT PRIMARY KEY, creator TEXT, first_seen INTEGER,
                                              created_ts INTEGER, older_than INTEGER, complete_ts INTEGER,
                                              curve INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sol_price (ts INTEGER PRIMARY KEY, usd REAL);
            CREATE TABLE IF NOT EXISTS stats (minute INTEGER PRIMARY KEY, total INTEGER, curve INTEGER,
                                              pumpswap INTEGER, other INTEGER);"""


def b58(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def decode(logs: list[str]) -> list[dict]:
    """The pump.fun / PumpSwap trade events in one transaction's logs."""
    out, stack = [], []
    for line in logs:
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "Program" and parts[2] == "invoke":
            stack.append(parts[1])
        elif len(parts) >= 3 and parts[0] == "Program" and parts[2] in ("success", "failed:"):
            if stack:
                stack.pop()
        if not line.startswith("Program data:"):
            continue
        program = stack[-1] if stack else None  # other Anchor programs reuse the event names (same discriminator)
        try:
            b = base64.b64decode(line.split(":", 1)[1].strip())
        except ValueError:
            continue
        if program == PUMP and b[:8] == TRADE and len(b) >= 121:
            # TradeEvent: mint, sol, token, is_buy, user, timestamp, virtual sol/token, real sol/token reserves,
            # fee recipient, fee bps, fee, creator, ... (offsets checked on live data: virtual - real = 30 SOL, 279.9M)
            sol, tok = struct.unpack_from("<QQ", b, 40)
            ts, vsol, vtok = struct.unpack_from("<qQQ", b, 89)
            rsol, rtok = struct.unpack_from("<QQ", b, 113) if len(b) >= 129 else (None, None)
            out.append({"venue": 1, "mint": b58(b[8:40]), "side": 1 if b[56] else 0, "user": b58(b[57:89]),
                        "lamports": sol, "tokens": tok, "ts": ts, "vsol": vsol, "vtok": vtok, "pool": None,
                        "rsol": rsol, "rtok": rtok, "creator": b58(b[177:209]) if len(b) >= 209 else None})
        elif program == PUMPSWAP and b[:8] in (BUY, SELL) and len(b) >= 184:
            # Buy/SellEvent: timestamp, base amount, limit, user reserves, pool base/quote reserves, quote amount,
            # fees..., pool, user, token accounts, protocol fee recipient (+ account), coin creator
            ts, base, _limit = struct.unpack_from("<qQQ", b, 8)
            pool_base, pool_quote, quote = struct.unpack_from("<QQQ", b, 48)  # quote: in (buy) / out (sell)
            out.append({"venue": 2, "mint": None, "side": 1 if b[:8] == BUY else 0, "user": b58(b[152:184]),
                        "lamports": quote, "tokens": base, "ts": ts, "vsol": pool_quote, "vtok": pool_base,
                        "pool": b58(b[120:152]), "rsol": None, "rtok": None,
                        "creator": b58(b[312:344]) if len(b) >= 344 else None})
    return out


class Collector:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, timeout=60)
        migrate(self.db)
        self.db.executescript(SCHEMA)
        self.pools = {p: b for p, b in self.db.execute("SELECT pool, base FROM pools")}
        # coins seen before the mints table existed: their creation time is looked up too
        self.db.execute("INSERT OR IGNORE INTO mints (mint, first_seen, curve) SELECT mint, MIN(ts), MAX(venue = 1) "
                        "FROM trades GROUP BY mint")
        self.db.commit()
        self.mints = {m: c for m, c in self.db.execute("SELECT mint, creator FROM mints")}
        self.curve_seen = {m for (m,) in self.db.execute("SELECT mint FROM mints WHERE curve = 1")}
        self.rows: list[tuple] = []
        self.minute = {"total": 0, "curve": 0, "pumpswap": 0, "other": 0}
        self.http = httpx.AsyncClient(timeout=20)
        self.unknown_pools: set[str] = set()

    async def pool_mint(self, pool: str) -> str | None:
        if pool in self.pools:
            return self.pools[pool]
        body = {"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo", "params": [pool, {"encoding": "base64"}]}
        try:
            res = (await self.http.post(HTTP_URL, json=body)).json()["result"]["value"]
            data = base64.b64decode(res["data"][0])
            base, quote = b58(data[43:75]), b58(data[75:107])  # Pool: disc 8, bump 1, index 2, creator 32, base, quote
        except Exception as exc:
            log.debug("pool %s unreadable: %s", pool, exc)
            return None
        self.pools[pool] = base
        self.db.execute("INSERT OR IGNORE INTO pools (pool, base, quote) VALUES (?, ?, ?)", (pool, base, quote))
        return base

    def note_mint(self, e: dict):
        mint, creator = e["mint"], e.get("creator")
        if mint not in self.mints:
            self.mints[mint] = creator
            self.db.execute("INSERT OR IGNORE INTO mints (mint, creator, first_seen) VALUES (?, ?, ?)",
                            (mint, creator, e["ts"]))
        elif creator and not self.mints[mint]:
            self.mints[mint] = creator
            self.db.execute("UPDATE mints SET creator = ? WHERE mint = ?", (creator, mint))
        if e["venue"] == 1 and mint not in self.curve_seen:
            self.curve_seen.add(mint)
            self.db.execute("UPDATE mints SET curve = 1 WHERE mint = ?", (mint,))
        if e["venue"] == 1 and e.get("rtok") == 0:
            self.db.execute("UPDATE mints SET complete_ts = ? WHERE mint = ? AND complete_ts IS NULL", (e["ts"], mint))

    async def on_logs(self, slot: int, sig: str, logs: list[str]):
        events = decode(logs)
        self.minute["total"] += 1
        venues = {e["venue"] for e in events}
        self.minute["curve" if 1 in venues else "pumpswap" if 2 in venues else "other"] += 1
        for e in events:
            if e["venue"] == 2:
                e["mint"] = await self.pool_mint(e["pool"])
                if e["mint"] is None:
                    continue
            self.note_mint(e)
            num = lambda x: None if x is None else float(x)  # noqa: E731  (u64 can exceed SQLite's integers)
            self.rows.append((slot, e["ts"], sig, e["venue"], e["mint"], e["side"], e["user"], num(e["lamports"]),
                              num(e["tokens"]), num(e["vsol"]), num(e["vtok"]), e["pool"], num(e["rsol"]),
                              num(e["rtok"])))

    def flush(self):
        if self.rows:
            self.db.executemany(f"INSERT INTO trades ({', '.join(TRADE_COLS)}) VALUES ({', '.join('?' * len(TRADE_COLS))})",
                                self.rows)
            self.rows = []
        self.db.commit()

    async def stream(self):
        async with websockets.connect(WS_URL, max_size=2 ** 24, ping_interval=20, ping_timeout=60) as ws:
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                      "params": [{"mentions": [FEE_PAYER]}, {"commitment": "confirmed"}]}))
            log.info("subscribed: %s", await ws.recv())
            last = time.time()
            async for raw in ws:
                msg = json.loads(raw)
                res = msg.get("params", {}).get("result", {})
                v = res.get("value") or {}
                if v and not v.get("err"):
                    await self.on_logs(res.get("context", {}).get("slot", 0), v.get("signature", ""), v.get("logs", []))
                if time.time() - last >= 2:
                    self.flush()
                    last = time.time()

    async def minute_loop(self):
        while True:
            await asyncio.sleep(60)
            m = int(time.time() // 60)
            self.db.execute("INSERT OR REPLACE INTO stats VALUES (?, ?, ?, ?, ?)",
                            (m, self.minute["total"], self.minute["curve"], self.minute["pumpswap"], self.minute["other"]))
            log.info("last minute: %s", self.minute)
            self.minute = dict.fromkeys(self.minute, 0)
            self.flush()

    async def price_loop(self):
        while True:
            try:
                usd = (await self.http.get(SOL_PRICE_URL)).json()["solana"]["usd"]
                self.db.execute("INSERT OR REPLACE INTO sol_price VALUES (?, ?)", (int(time.time()), float(usd)))
            except Exception as exc:
                log.debug("SOL price unavailable: %s", exc)
            await asyncio.sleep(300)

    async def rpc(self, method: str, params: list):
        """One call to the free RPC, waiting and retrying while it answers 429."""
        for attempt in range(6):
            res = (await self.http.post(HTTP_URL, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                                         "params": params})).json()
            if "error" not in res:
                return res["result"]
            if res["error"].get("code") != 429:
                raise RuntimeError(res["error"])
            await asyncio.sleep(5 * (attempt + 1))
        raise RuntimeError("429")

    async def oldest(self, account: str) -> tuple[int | None, int | None]:
        """(time of the account's oldest transaction, None) or (None, oldest time seen) when cut at MAX_PAGES."""
        before, last = None, None
        for _ in range(MAX_PAGES):
            sigs = await self.rpc("getSignaturesForAddress", [account, {"limit": 1000, **({"before": before} if before else {})}])
            await asyncio.sleep(LOOKUP_GAP)
            if not sigs:
                return (last, None) if last is not None else (None, None)
            last = sigs[-1].get("blockTime")
            if len(sigs) < 1000:
                return last, None
            before = sigs[-1]["signature"]
        return None, last

    async def lookup_loop(self):
        """Creation times: coins seen on their curve (newest first), their pools (graduation), then the rest."""
        while True:
            todo = "created_ts IS NULL AND older_than IS NULL"
            row = None
            for sql in (f"SELECT 'mints', mint FROM mints WHERE curve = 1 AND {todo} ORDER BY first_seen DESC LIMIT 1",
                        f"SELECT 'pools', pool FROM pools WHERE {todo} AND base IN (SELECT mint FROM mints WHERE curve = 1) "
                        "LIMIT 1",
                        f"SELECT 'mints', mint FROM mints WHERE {todo} ORDER BY first_seen DESC LIMIT 1",
                        f"SELECT 'pools', pool FROM pools WHERE {todo} LIMIT 1"):
                row = self.db.execute(sql).fetchone()
                if row:
                    break
            if row is None:
                await asyncio.sleep(10)
                continue
            table, account = row
            key = "mint" if table == "mints" else "pool"
            try:
                created, older = await self.oldest(account)
            except Exception as exc:
                log.debug("lookup %s failed: %s", account, exc)
                created, older = None, -1  # not retried (-1 = unknown)
            if created is None and older is None:
                older = -1
            self.db.execute(f"UPDATE {table} SET created_ts = ?, older_than = ? WHERE {key} = ?", (created, older, account))
            self.db.commit()

    async def run(self):
        asyncio.create_task(self.minute_loop())
        asyncio.create_task(self.price_loop())
        asyncio.create_task(self.lookup_loop())
        while True:
            try:
                await self.stream()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("websocket dropped (%s); reconnecting", exc)
                self.flush()
                await asyncio.sleep(5)


def migrate(db: sqlite3.Connection):
    """Columns added after the collector first ran on the server."""
    for table, cols in (("trades", ("rsol REAL", "rtok REAL")), ("pools", ("created_ts INTEGER", "older_than INTEGER")),
                        ("mints", ("curve INTEGER DEFAULT 0",))):
        have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        if have:
            for c in cols:
                if c.split()[0] not in have:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {c}")
    db.commit()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(Collector(sys.argv[1] if len(sys.argv) > 1 else "solana.db").run())


if __name__ == "__main__":
    main()
