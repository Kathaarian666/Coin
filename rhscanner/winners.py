"""Coins that ran 10x+ lately, and what the bot saw of them (/kazananlar).

GeckoTerminal (free, ~30 calls/min) lists the chain's busiest and trending
pools and serves hourly candles, so a coin's run can be measured from its
first candle. Each winner is then looked up in the outcome log: alerted,
held back by the filters, only in the shadow group, or never seen.
"""

import asyncio
import calendar
import logging
import time

import httpx

log = logging.getLogger(__name__)

GECKOTERMINAL = "https://api.geckoterminal.com/api/v2/networks/robinhood"
PAUSE_SEC = 2.5  # stay under the free tier's ~30 calls a minute
MAX_CANDIDATES = 30
MIN_VOLUME_H24 = 20_000
MIN_CANDLE_USD = 1_000  # thinner hours are ignored: on shallow pools one trade makes a wild print
MIN_PEAK_FDV = 50_000  # below that a "100x" was never tradeable


class GeckoTerminal:
    def __init__(self, http: httpx.AsyncClient, pause: float = PAUSE_SEC):
        self.http = http
        self.pause = pause

    async def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(4):
            await asyncio.sleep(self.pause)
            try:
                resp = await self.http.get(f"{GECKOTERMINAL}/{path}", params=params,
                                           headers={"Accept": "application/json"})
                if resp.status_code == 429:
                    await asyncio.sleep(15 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("geckoterminal %s failed: %s", path, exc)
        return {}

    async def pools(self, volume_pages: int = 3, trending_pages: int = 1) -> list[dict]:
        """Busiest and trending pools, one per token (the busiest)."""
        raw = []
        for page in range(1, trending_pages + 1):
            raw += (await self._get("trending_pools", {"duration": "24h", "page": page})).get("data", [])
        for page in range(1, volume_pages + 1):
            raw += (await self._get("pools", {"page": page, "sort": "h24_volume_usd_desc"})).get("data", [])
        by_token: dict[str, dict] = {}
        for item in raw:
            pool = parse_pool(item)
            if pool and pool["volume_h24"] > by_token.get(pool["token"], {}).get("volume_h24", -1):
                by_token[pool["token"]] = pool
        return list(by_token.values())

    async def hourly(self, pool: str, limit: int = 200) -> list[list[float]]:
        """[ts, open, high, low, close, volume] per hour, oldest first."""
        data = await self._get(f"pools/{pool}/ohlcv/hour", {"aggregate": 1, "limit": limit, "currency": "usd"})
        rows = ((data.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        return sorted(rows, key=lambda r: r[0])


def parse_pool(item: dict) -> dict | None:
    attrs = item.get("attributes") or {}
    base = (((item.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id", "")
    created = attrs.get("pool_created_at")
    if not base or not attrs.get("address") or not created:
        return None
    try:
        created_ts = float(calendar.timegm(time.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        return None
    return {
        "pool": attrs["address"],
        "token": base.split("_", 1)[-1].lower(),
        "symbol": (attrs.get("name") or "?").split(" / ")[0],
        "created": created_ts,
        "volume_h24": float((attrs.get("volume_usd") or {}).get("h24") or 0),
        "fdv": float(attrs.get("fdv_usd") or 0) or None,
    }


def run_of(candles: list[list[float]], fdv_now: float | None = None) -> dict | None:
    """The run from the first traded hour's close to the highest close (hourly closes, thin hours skipped)."""
    traded = [c for c in candles if (c[5] or 0) >= MIN_CANDLE_USD and c[4]]
    if len(traded) < 2:
        return None
    start, peak = traded[0], max(traded, key=lambda c: c[4])
    last = candles[-1][4]
    return {"start": start[4], "start_ts": start[0], "peak": peak[4], "peak_ts": peak[0],
            "multiple": peak[4] / start[4], "hours_to_peak": (peak[0] - start[0]) / 3600,
            "peak_fdv": fdv_now * peak[4] / last if fdv_now and last else None}


def entry_of(candles: list[list[float]], run: dict, signal_ts: float, p0: float | None) -> dict:
    """Where in the run a signal came: price vs the run's start, and the best hourly close after it."""
    if not p0:
        return {}
    after = [c[4] for c in candles if c[0] + 3600 > signal_ts and (c[5] or 0) >= MIN_CANDLE_USD]
    return {"entry_vs_start": p0 / run["start"], "peak_after": max(after) / p0 if after else None,
            "before_peak": signal_ts < run["peak_ts"] + 3600}


async def find_winners(gecko: GeckoTerminal, outcomes, days: float, min_multiple: float,
                       now: float | None = None) -> tuple[list[dict], int]:
    """Coins that ran at least `min_multiple` since launch within `days`; returns (winners, pools checked)."""
    now = now or time.time()
    pools = [p for p in await gecko.pools()
             if p["created"] >= now - days * 86400 and p["volume_h24"] >= MIN_VOLUME_H24]
    pools = sorted(pools, key=lambda p: -p["volume_h24"])[:MAX_CANDIDATES]
    winners = []
    for pool in pools:
        candles = await gecko.hourly(pool["pool"])
        run = run_of(candles, pool.get("fdv"))
        if not run or run["multiple"] < min_multiple or (run["peak_fdv"] or 0) < MIN_PEAK_FDV:
            continue
        seen = outcomes.signals_for(pool["token"], ("alert", "filtered", "shadow"))
        for s in seen:
            s.update(entry_of(candles, run, s["ts"], s["p0"]))
        winners.append({**pool, **run, "signals": seen})
    winners.sort(key=lambda w: -w["multiple"])
    return winners, len(pools)
