"""Pons coins before graduation: trading on their bonding curves, read from the chain.

Every Pons V2 coin is born on its own bonding-curve contract (the launch
event's topic2, kept in launches.py) and trades there until it graduates to a
DEX pool; DexScreener does not list it before that. Each curve emits

  CurveBuy(address indexed router, address indexed buyer, uint256 eth, uint256 tokens, uint256 fee, uint256 tax)
  CurveSell(address indexed router, address indexed seller, uint256 tokens, uint256 eth, uint256 fee, uint256 tax)

so one topic-filtered log query per poll covers every curve on the chain.
Thousands of coins launch a day and most are junk; `junk_reasons` drops the
obvious cases from what little is known this early (who launched it, who buys).
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import httpx

from .rpc import RetryableHttpError, RpcClient

log = logging.getLogger(__name__)

CURVE_BUY = "0xec36bf571f136799e8dc0b0b8bea4b04d8bd3d43de838aab0d5fc21d4cbfc455"
CURVE_SELL = "0x8113d738abdcb6b38357e9d53a54a7157861a09031b453651f0fe7fe151f59df"
BLOCKS_PER_MIN = 600  # ~10 blocks/s
DAY_BLOCKS_PONS = 24 * 60 * BLOCKS_PER_MIN
EARLY_BLOCKS = 30  # ~3 s after the launch: snipers and bundles
PRICE_MAX_AGE = 25 * 3600  # long enough for the 24 h outcome samples

# Obvious junk (thresholds are first guesses; every value is recorded so /karne can calibrate them).
SERIAL_LAUNCHES_24H = 10  # the launcher made this many coins in the last day
TOP_BUYER_SHARE = 0.5  # one wallet paid half of all buying
EARLY_SHARE = 0.5  # half of all buying came in the first seconds
DEV_BUY_SHARE = 0.3  # the launcher's own buys
SELL_RATIO = 0.8  # sold back nearly as much ETH as was bought
BUYS_PER_BUYER = 4.0  # the same wallets buying again and again (wash)


@dataclass
class CurveTrade:
    curve: str  # lowercased
    trader: str  # lowercased
    side: str  # "buy" | "sell"
    eth: float
    tokens: float
    block: int
    timestamp: float = 0.0


def parse_curve_logs(logs: list[dict]) -> list[CurveTrade]:
    trades = []
    for entry in logs:
        topics = entry.get("topics") or []
        data = entry.get("data") or "0x"
        if len(topics) < 3 or len(data) < 2 + 128:
            continue
        kind = topics[0].lower()
        first, second = int(data[2:66], 16) / 1e18, int(data[66:130], 16) / 1e18
        if kind == CURVE_BUY:
            side, eth, tokens = "buy", first, second
        elif kind == CURVE_SELL:
            side, eth, tokens = "sell", second, first
        else:
            continue
        trades.append(CurveTrade(entry["address"].lower(), "0x" + topics[2][-40:].lower(), side, eth, tokens,
                                 int(entry["blockNumber"], 16)))
    return trades


class PonsTracker:
    """Recent trades per curve, and each curve's last trade price (ETH per token)."""

    def __init__(self, max_age: float = 7200):
        self.max_age = max_age
        self.trades: dict[str, deque[CurveTrade]] = defaultdict(deque)
        self.prices: dict[str, tuple[float, float]] = {}

    def add(self, trade: CurveTrade):
        self.trades[trade.curve].append(trade)
        if trade.tokens > 0:
            self.prices[trade.curve] = (trade.eth / trade.tokens, trade.timestamp or time.time())

    def price(self, curve: str) -> float | None:
        entry = self.prices.get(curve.lower())
        return entry[0] if entry else None

    def prune(self, now: float | None = None):
        now = now or time.time()
        for curve in list(self.trades):
            kept = deque(t for t in self.trades[curve] if t.timestamp >= now - self.max_age)
            if kept:
                self.trades[curve] = kept
            else:
                del self.trades[curve]
        for curve, (_, ts) in list(self.prices.items()):
            if ts < now - PRICE_MAX_AGE:
                del self.prices[curve]

    def stats(self, curve: str, launcher: str, launch_block: int, window_sec: float, now: float | None = None) -> dict:
        """Buying in the window, plus whole-history shares (everything seen since the launch, up to max_age)."""
        now = now or time.time()
        trades = list(self.trades.get(curve.lower(), ()))
        buys = [t for t in trades if t.side == "buy"]
        sells = [t for t in trades if t.side == "sell"]
        recent = [t for t in buys if t.timestamp >= now - window_sec and t.trader != launcher]
        buy_eth = sum(t.eth for t in buys) or 0.0
        per_buyer: dict[str, float] = defaultdict(float)
        for t in buys:
            if t.trader != launcher:
                per_buyer[t.trader] += t.eth
        share = lambda eth: round(eth / buy_eth, 3) if buy_eth else 0.0  # noqa: E731
        return {
            "buyers_10m": len({t.trader for t in recent}),
            "buy_eth_10m": round(sum(t.eth for t in recent), 4),
            "buyers": len(per_buyer),
            "buys": len(buys),
            "sells": len(sells),
            "buy_eth": round(buy_eth, 4),
            "sell_eth": round(sum(t.eth for t in sells), 4),
            "top_buyer_share": share(max(per_buyer.values(), default=0.0)),
            "dev_buy_share": share(sum(t.eth for t in buys if t.trader == launcher)),
            "early_share": share(sum(t.eth for t in buys
                                     if t.block <= launch_block + EARLY_BLOCKS and t.trader != launcher)),
            "dev_sold": any(t.trader == launcher for t in sells),
        }


def junk_reasons(stats: dict, launches_24h: int) -> list[str]:
    reasons = []
    if launches_24h >= SERIAL_LAUNCHES_24H:
        reasons.append("seri_dev")
    if stats["dev_sold"]:
        reasons.append("dev_satti")
    if stats["dev_buy_share"] >= DEV_BUY_SHARE:
        reasons.append("dev_alimi")
    if stats["top_buyer_share"] >= TOP_BUYER_SHARE:
        reasons.append("tek_alici")
    if stats["early_share"] >= EARLY_SHARE:
        reasons.append("erken_kume")
    if stats["buy_eth"] and stats["sell_eth"] >= SELL_RATIO * stats["buy_eth"]:
        reasons.append("satis_baskisi")
    if stats["buyers"] and stats["buys"] / stats["buyers"] >= BUYS_PER_BUYER:
        reasons.append("tekrar_alim")
    return reasons


async def fetch_curve_logs(rpc: RpcClient, from_block: int, to_block: int) -> list[dict]:
    """Buys and sells on every curve, halving the range when the node refuses it."""
    try:
        return await rpc.get_logs(from_block, to_block, [[CURVE_BUY, CURVE_SELL]], retries=1)
    except Exception:
        if to_block - from_block < 50:
            raise
        mid = (from_block + to_block) // 2
        return await fetch_curve_logs(rpc, from_block, mid) + await fetch_curve_logs(rpc, mid + 1, to_block)


class PonsWatcher:
    """Polls curve trades and feeds them to a callback, like fomo.FomoWatcher."""

    def __init__(self, rpc: RpcClient, settings, storage, tracker: PonsTracker):
        self.rpc = rpc
        self.settings = settings
        self.storage = storage
        self.tracker = tracker

    async def run(self, on_trades):
        saved = self.storage.get_state("pons_last_block")
        head = await self.rpc.block_number()
        next_block = max(0, head - self.settings.pons_lookback_blocks)
        if saved is not None:
            next_block = max(next_block, int(saved) + 1)
        warmup_until = head  # trades up to here only fill the window
        log.info("watching Pons curve trades from block %d", next_block)
        while True:
            try:
                head = await self.rpc.block_number()
                while next_block <= head:
                    to_block = min(head, next_block + 1999)
                    trades = parse_curve_logs(await fetch_curve_logs(self.rpc, next_block, to_block))
                    stamp = await self.rpc.block_timestamp(to_block)
                    for trade in trades:
                        trade.timestamp = stamp
                        self.tracker.add(trade)
                    self.storage.set_state("pons_last_block", str(to_block))
                    next_block = to_block + 1
                    if trades:
                        await on_trades(trades, to_block <= warmup_until)
                self.tracker.prune()
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, RetryableHttpError) as exc:
                log.warning("Pons polling failed (%s); will retry", exc)
            except Exception:
                log.exception("Pons polling failed; will retry")
            await asyncio.sleep(self.settings.pons_poll_interval)
