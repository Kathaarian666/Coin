"""Full-market pump.fun trades (every wallet, not only Fomo's) for chosen coins and time windows, from pump.fun's own
free API (PROJE.md §4.5e). Fomo users make only ~3-6 % of a pump.fun coin's volume, so the Fomo collector
(rhscanner/solana.py) sees the price only now and then; fast pump-and-dumps happen in between.

  python scripts/pump_fetch.py trades <windows.csv> <out.jsonl>
  python scripts/pump_fetch.py candles <mints.csv> <out.jsonl>     1-minute candles (one request a coin)
  python scripts/pump_fetch.py gecko <pools.csv> <out.jsonl>       1-minute candles from GeckoTerminal for a window

windows.csv: mint, slot, ts_start, ts_end (UTC seconds; slot = any Solana slot near ts_start, from our data). The API
pages newest to oldest, 100 trades a page; its cursor is "<slot>-<ms>", so a page can start at any past moment: the
end slot is estimated from the known one (0.4 s a slot) plus a margin, and trades after ts_end are dropped. ~1 page/s
(it answers 429 faster), waits and retries; out.jsonl gets one line per finished coin, and coins already in it are
skipped (resumable). A line: {"mint", "ts_start", "ts_end", "trades": [[ts, side 1 buy / 0 sell, user, program
(pump / pump_amm), sol, usd, tokens, price_usd], ...]} oldest first; pages: how many were read.
candles: the coin's last 1000 one-minute candles (minutes with trades only), every wallet's trades, USD per token
(6 decimals): {"mint", "candles": [[ts, open, high, low, close, volume_usd], ...]} oldest first. A coin that traded
in fewer than 1000 minutes comes whole, from its creation; prices match the chain (the curve's reserves) to 0.1 %.
The API allows ~20 requests a minute from one address (429 with Retry-After beyond; an early retry often passes).
gecko: pump.fun's candles stop at the last 1000 active minutes, so a coin that stayed busy (the winners) does not
reach back to its graduation; GeckoTerminal's minute candles of its PumpSwap pool page back in time (pools.csv: mint,
pool, ts_start, ts_end; ~30 requests a minute, 1000 candles each), same line format.
"""

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://swap-api.pump.fun/v2/coins/{mint}/trades?limit=100&cursor={cursor}"
CANDLES = "https://swap-api.pump.fun/v2/coins/{mint}/candles?interval=1m&limit=1000&currency=USD&createdTs=1"
GECKO = ("https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/minute?aggregate=1&limit=1000"
         "&currency=usd&token=base&before_timestamp={before}")
GAP = 1.0  # s between requests
SLOT_S = 0.4
MAX_PAGES = 400  # per coin window (a very busy coin is cut short; "complete": false)


def get(url: str):
    for k in range(8):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(3 * (k + 1))
    raise RuntimeError(f"gave up: {url}")


def ts_of(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def fetch(mint: str, slot: int, ts_start: float, ts_end: float) -> dict:
    end_slot = int(slot + (ts_end - ts_start) / SLOT_S + 300)  # a bit past the end: slot times drift
    cursor = f"{end_slot}-{int(ts_end + 120) * 1000}"
    rows, pages, complete = [], 0, False
    while pages < MAX_PAGES:
        x = get(API.format(mint=mint, cursor=cursor))
        pages += 1
        time.sleep(GAP)
        for tr in x.get("trades", []):
            t = ts_of(tr["timestamp"])
            if t < ts_start:
                complete = True
                break
            if t <= ts_end:
                rows.append([t, 1 if tr["type"] == "buy" else 0, tr["userAddress"], tr["program"],
                             float(tr["amountSol"]), float(tr["amountUsd"]), float(tr["baseAmount"]),
                             float(tr["priceUsd"])])
        if complete or not x.get("trades") or not x.get("pagination", {}).get("hasMore"):
            complete = True
            break
        cursor = x["pagination"]["nextCursor"]
    rows.reverse()
    return {"mint": mint, "ts_start": ts_start, "ts_end": ts_end, "pages": pages, "complete": complete, "trades": rows}


def candles(mint: str) -> dict:
    x = get(CANDLES.format(mint=mint))
    time.sleep(GAP)
    keys = ("open", "high", "low", "close", "volume")
    return {"mint": mint, "candles": [[c["timestamp"] // 1000, *(float(c[k]) for k in keys)] for c in x
                                      if all(c.get(k) is not None for k in keys)]}


def gecko(mint: str, pool: str, ts_start: float, ts_end: float) -> dict:
    out, before = [], int(ts_end) + 60
    for _ in range(20):
        if before <= ts_start:
            break
        x = get(GECKO.format(pool=pool, before=before))["data"]["attributes"]["ohlcv_list"]
        time.sleep(2.1)
        oldest = int(min(c[0] for c in x)) if x else before
        if oldest >= before:  # nothing older: the pool's start
            break
        out += x
        before = oldest
    return {"mint": mint, "candles": sorted([int(c[0]), *map(float, c[1:6])] for c in out if c[0] <= ts_end)}


def main():
    mode, src, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    done = set()
    if out.exists():
        done = {json.loads(line)["mint"] for line in out.open()}
    todo = [r for r in csv.DictReader(src.open()) if r["mint"] not in done]
    print(f"{len(done)} hazır, {len(todo)} kaldı", flush=True)
    t0 = time.time()
    with out.open("a") as f:
        for i, r in enumerate(todo, 1):
            if mode == "candles":
                res = candles(r["mint"])
            elif mode == "gecko":
                res = gecko(r["mint"], r["pool"], float(r["ts_start"]), float(r["ts_end"]))
            else:
                res = fetch(r["mint"], int(float(r["slot"])), float(r["ts_start"]), float(r["ts_end"]))
            f.write(json.dumps(res) + "\n")
            f.flush()
            if i % 100 == 0:
                print(f"{i}/{len(todo)} coin, {(time.time() - t0) / i:.1f} sn/coin", flush=True)


if __name__ == "__main__":
    main()
