"""Fomo order flow on Robinhood Chain, read straight from the chain.

Fomo trades run as ERC-4337 user operations through two contracts that emit
the same event for every leg of a trade (found by tracing a Fomo user's
buys; ~4k buys/hour by ~2.7k distinct users at the time of writing):

  entry    FOMO_ENTRY     user -> executor   (what the user pays in)
  executor FOMO_EXECUTOR  executor -> user   (what the user receives)

A buy pays USDG (or ETH) in and delivers the token out; a sell does the
reverse. Counting distinct buyers per token gives a live "trending on Fomo"
signal without any Fomo account or API.
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import httpx
from eth_utils import to_checksum_address

from .config import USDG
from .rpc import RpcClient

log = logging.getLogger(__name__)

FOMO_ENTRY = "0xccc88a9d1b4ed6b0eaba998850414b24f1c315be"
FOMO_EXECUTOR = "0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f"
# Event(address from, address to, address token, uint256 amount, bytes ref), none indexed.
FOMO_TRANSFER_TOPIC = "0xafbab204e8271965231d37baed9b1abca8725b7409c70314455f68bc89142b91"

_USDG = USDG.lower()
_ETH = "0x" + "0" * 40
_CASH = {_USDG, _ETH}


@dataclass
class FomoTrade:
    tx_hash: str
    block: int
    token: str  # checksummed
    side: str  # "buy" | "sell"
    trader: str  # lowercased
    usd: float | None = None
    timestamp: float = 0.0


def _words(data: str) -> list[str]:
    body = data[2:]
    return [body[i: i + 64] for i in range(0, len(body) - 63, 64)]


def _addr(word: str) -> str:
    return "0x" + word[-40:]


def parse_fomo_logs(logs: list[dict]) -> list[FomoTrade]:
    """Group the Fomo events of each transaction into buys and sells."""
    by_tx: dict[str, list[dict]] = defaultdict(list)
    for entry in logs:
        if entry.get("topics") and entry["topics"][0].lower() == FOMO_TRANSFER_TOPIC:
            by_tx[entry["transactionHash"]].append(entry)

    trades = []
    for tx_hash, entries in by_tx.items():
        legs = []
        for entry in entries:
            words = _words(entry["data"])
            if len(words) < 4:
                continue
            legs.append({
                "emitter": entry["address"].lower(),
                "from": _addr(words[0]),
                "to": _addr(words[1]),
                "token": _addr(words[2]),
                "amount": int(words[3], 16),
                "block": int(entry["blockNumber"], 16),
            })
        # USDG moving through the trade = its dollar size (USDG has 6 decimals).
        usdg = [leg["amount"] for leg in legs if leg["token"] == _USDG]
        usd = max(usdg) / 1e6 if usdg else None
        for leg in legs:
            if leg["token"] in _CASH:
                continue
            if leg["from"] == FOMO_EXECUTOR and leg["to"] != FOMO_EXECUTOR:
                side, trader = "buy", leg["to"]
            elif leg["emitter"] == FOMO_ENTRY and leg["to"] == FOMO_EXECUTOR:
                side, trader = "sell", leg["from"]
            else:
                continue
            trades.append(FomoTrade(tx_hash, leg["block"], to_checksum_address(leg["token"]), side, trader, usd))
    return trades


class FomoTracker:
    """Rolling per-token statistics of Fomo trades."""

    def __init__(self, max_age: float = 3600):
        self.max_age = max_age
        self.trades: dict[str, deque[FomoTrade]] = defaultdict(deque)
        self.first_seen: dict[str, float] = {}

    def add(self, trade: FomoTrade):
        key = trade.token.lower()
        self.trades[key].append(trade)
        self.first_seen.setdefault(key, trade.timestamp)

    def prune(self, now: float | None = None):
        cutoff = (now or time.time()) - self.max_age
        for key in list(self.trades):
            kept = deque(t for t in self.trades[key] if t.timestamp >= cutoff)
            if kept:
                self.trades[key] = kept
            else:
                del self.trades[key]

    def stats(self, token: str, window_sec: float, now: float | None = None) -> dict:
        now = now or time.time()
        recent = [t for t in self.trades.get(token.lower(), ()) if t.timestamp >= now - window_sec]
        buys = [t for t in recent if t.side == "buy"]
        sells = [t for t in recent if t.side == "sell"]
        return {
            "window_min": round(window_sec / 60, 1),
            "buyers": len({t.trader for t in buys}),
            "sellers": len({t.trader for t in sells}),
            "buys": len(buys),
            "sells": len(sells),
            "buy_usd": round(sum(t.usd or 0 for t in buys), 2),
            "sell_usd": round(sum(t.usd or 0 for t in sells), 2),
            "first_seen": self.first_seen.get(token.lower()),
        }

    def top(self, window_sec: float, limit: int = 10, now: float | None = None) -> list[tuple[str, dict]]:
        rows = [(token, self.stats(token, window_sec, now)) for token in self.trades]
        rows = [r for r in rows if r[1]["buyers"]]
        rows.sort(key=lambda r: (r[1]["buyers"], r[1]["buy_usd"]), reverse=True)
        return [(to_checksum_address(t), s) for t, s in rows[:limit]]


class FomoWatcher:
    """Polls the Fomo contracts' events and feeds trades to a callback."""

    def __init__(self, rpc: RpcClient, settings, storage, tracker: FomoTracker):
        self.rpc = rpc
        self.settings = settings
        self.storage = storage
        self.tracker = tracker

    async def _fetch(self, from_block: int, to_block: int) -> list[dict]:
        """eth_getLogs, halving the range when the node refuses a large result."""
        try:
            return await self.rpc.get_logs(
                from_block, to_block, [FOMO_TRANSFER_TOPIC], address=[FOMO_ENTRY, FOMO_EXECUTOR], retries=1
            )
        except Exception:
            if to_block - from_block < 50:
                raise
            mid = (from_block + to_block) // 2
            return await self._fetch(from_block, mid) + await self._fetch(mid + 1, to_block)

    async def run(self, on_trades):
        saved = self.storage.get_state("fomo_last_block")
        head = await self.rpc.block_number()
        # Always warm up the rolling window, even after a restart.
        next_block = max(0, head - self.settings.fomo_lookback_blocks)
        if saved is not None:
            next_block = max(next_block, int(saved) + 1)
        warmup_until = head  # trades up to here only fill the window; they are not "new"
        log.info("watching Fomo trades from block %d", next_block)
        while True:
            try:
                head = await self.rpc.block_number()
                while next_block <= head:
                    to_block = min(head, next_block + 2999)
                    trades = parse_fomo_logs(await self._fetch(next_block, to_block))
                    stamp = await self.rpc.block_timestamp(to_block)
                    for trade in trades:
                        trade.timestamp = stamp
                        self.tracker.add(trade)
                    self.storage.set_state("fomo_last_block", str(to_block))
                    next_block = to_block + 1
                    if trades:
                        await on_trades(trades, to_block <= warmup_until)
                self.tracker.prune()
            except asyncio.CancelledError:
                raise
            except httpx.HTTPError as exc:
                log.warning("Fomo polling failed (%s); will retry", exc)
            except Exception:
                log.exception("Fomo polling failed; will retry")
            await asyncio.sleep(self.settings.poll_interval)
