"""Solana collector (PROJE.md §4.5, step 6): every Fomo trade on pump.fun and PumpSwap, live, into SQLite.

  python -m rhscanner.solana [<db>=solana.db]

Fomo signs and pays gas for all of its Solana trades with one wallet (FEE_PAYER), so the public websocket's
logsSubscribe(mentions=[FEE_PAYER]) streams them all for free. The logs carry the venues' Anchor events:
- pump.fun bonding curve TradeEvent: mint, SOL, tokens, buy/sell, user, time, the curve's virtual reserves
- PumpSwap (graduated pump.fun coins) BuyEvent / SellEvent: time, base/quote amounts, pool, user; the pool's base
  mint is read once per pool (getAccountInfo) and cached
Other venues (Meteora, Raydium, ...) are counted but not stored yet. SOL/USD is sampled every 5 minutes.
Table trades(slot, ts, sig, venue 1 curve / 2 pumpswap, mint, side 1 buy / 0 sell, user, lamports, tokens,
vsol, vtok, pool); amounts are stored as REAL (u64 can exceed SQLite's integers). Tokens are raw units (pump.fun coins have 6 decimals), lamports = SOL * 1e9.
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


def _disc(name: str) -> bytes:
    return hashlib.sha256(f"event:{name}".encode()).digest()[:8]


TRADE, BUY, SELL = _disc("TradeEvent"), _disc("BuyEvent"), _disc("SellEvent")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

SCHEMA = """CREATE TABLE IF NOT EXISTS trades (slot INTEGER, ts INTEGER, sig TEXT, venue INTEGER, mint TEXT,
            side INTEGER, user TEXT, lamports REAL, tokens REAL, vsol REAL, vtok REAL, pool TEXT);
            CREATE INDEX IF NOT EXISTS trades_mint ON trades (mint, ts);
            CREATE TABLE IF NOT EXISTS pools (pool TEXT PRIMARY KEY, base TEXT, quote TEXT);
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
            sol, tok = struct.unpack_from("<QQ", b, 40)
            ts, vsol, vtok = struct.unpack_from("<qQQ", b, 89)
            out.append({"venue": 1, "mint": b58(b[8:40]), "side": 1 if b[56] else 0, "user": b58(b[57:89]),
                        "lamports": sol, "tokens": tok, "ts": ts, "vsol": vsol, "vtok": vtok, "pool": None})
        elif program == PUMPSWAP and b[:8] in (BUY, SELL) and len(b) >= 184:
            ts, base, _limit = struct.unpack_from("<qQQ", b, 8)
            buy = b[:8] == BUY
            quote = struct.unpack_from("<Q", b, 8 + 8 * 7)[0]  # quote_amount_in (buy) / quote_amount_out (sell)
            out.append({"venue": 2, "mint": None, "side": 1 if buy else 0, "user": b58(b[152:184]),
                        "lamports": quote, "tokens": base, "ts": ts, "vsol": None, "vtok": None,
                        "pool": b58(b[120:152])})
    return out


class Collector:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, timeout=60)
        self.db.executescript(SCHEMA)
        self.pools = {p: b for p, b, _ in self.db.execute("SELECT pool, base, quote FROM pools")}
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
        self.db.execute("INSERT OR REPLACE INTO pools VALUES (?, ?, ?)", (pool, base, quote))
        return base

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
            num = lambda x: None if x is None else float(x)  # noqa: E731  (u64 can exceed SQLite's integers)
            self.rows.append((slot, e["ts"], sig, e["venue"], e["mint"], e["side"], e["user"], num(e["lamports"]),
                              num(e["tokens"]), num(e["vsol"]), num(e["vtok"]), e["pool"]))

    def flush(self):
        if self.rows:
            self.db.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", self.rows)
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

    async def run(self):
        asyncio.create_task(self.minute_loop())
        asyncio.create_task(self.price_loop())
        while True:
            try:
                await self.stream()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("websocket dropped (%s); reconnecting", exc)
                self.flush()
                await asyncio.sleep(5)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(Collector(sys.argv[1] if len(sys.argv) > 1 else "solana.db").run())


if __name__ == "__main__":
    main()
