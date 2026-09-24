"""Smart Fomo wallets: traders whose recent round trips mostly made money.

Every Fomo trade is folded into a per-(wallet, token) position: USD and token
amount bought and sold. A position counts as closed once its trader has sold,
and its return is what the sale fetched against the cost of the tokens sold.
Wallets with enough closed positions, a good win rate and positive realized
PnL over the last few days are "smart". On Fomo others can follow them and get
their buys as notifications, so their buying tends to pull more buyers in,
which is why it feeds the short-term momentum score (with a low weight: the
research finds successful-trader presence to be a weak signal on its own).
"""

import logging
import time
from dataclasses import dataclass

from .fomo import FomoTrade, FomoTracker

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS fomo_positions (
    wallet TEXT NOT NULL,
    token TEXT NOT NULL,
    buy_usd REAL NOT NULL DEFAULT 0,
    buy_amount REAL NOT NULL DEFAULT 0,
    sell_usd REAL NOT NULL DEFAULT 0,
    sell_amount REAL NOT NULL DEFAULT 0,
    first_ts REAL NOT NULL,
    last_ts REAL NOT NULL,
    PRIMARY KEY (wallet, token)
);
CREATE INDEX IF NOT EXISTS fomo_positions_last ON fomo_positions (last_ts);
"""

LOOKBACK_DAYS = 7
MIN_CLOSED = 5
MIN_WIN_RATE = 0.55
MIN_PNL_USD = 100.0
WIN_ROI = 1.1  # a round trip counts as a win above +10%


@dataclass
class WalletStats:
    wallet: str
    closed: int
    wins: int
    pnl_usd: float

    @property
    def win_rate(self) -> float:
        return self.wins / self.closed if self.closed else 0.0


class WalletBook:
    def __init__(self, db):
        self.db = db
        self.db.executescript(SCHEMA)
        self.db.commit()
        self.smart: dict[str, WalletStats] = {}

    def add(self, trades: list[FomoTrade]):
        """Fold trades into positions. Trades without a USD value (paid in ETH) are skipped."""
        for t in trades:
            if not t.usd or not t.amount:
                continue
            buy = t.side == "buy"
            self.db.execute(
                """INSERT INTO fomo_positions (wallet, token, buy_usd, buy_amount, sell_usd, sell_amount, first_ts, last_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (wallet, token) DO UPDATE SET
                     buy_usd = buy_usd + excluded.buy_usd, buy_amount = buy_amount + excluded.buy_amount,
                     sell_usd = sell_usd + excluded.sell_usd, sell_amount = sell_amount + excluded.sell_amount,
                     last_ts = excluded.last_ts""",
                (t.trader, t.token.lower(), t.usd if buy else 0, float(t.amount) if buy else 0.0,  # raw amounts overflow int64
                 0 if buy else t.usd, 0.0 if buy else float(t.amount), t.timestamp, t.timestamp),
            )
        self.db.commit()

    def stats(self, now: float | None = None) -> list[WalletStats]:
        since = (now or time.time()) - LOOKBACK_DAYS * 86400
        rows = self.db.execute(
            "SELECT wallet, buy_usd, buy_amount, sell_usd, sell_amount FROM fomo_positions "
            "WHERE last_ts >= ? AND sell_amount > 0 AND buy_amount > 0",
            (since,),
        ).fetchall()
        per_wallet: dict[str, WalletStats] = {}
        for wallet, buy_usd, buy_amount, sell_usd, sell_amount in rows:
            sold_share = min(1.0, sell_amount / buy_amount)
            cost = buy_usd * sold_share
            if cost <= 0:
                continue
            s = per_wallet.setdefault(wallet, WalletStats(wallet, 0, 0, 0.0))
            s.closed += 1
            s.wins += sell_usd / cost >= WIN_ROI
            s.pnl_usd += sell_usd - cost
        return list(per_wallet.values())

    def refresh(self, now: float | None = None):
        """Recompute the smart set and drop positions older than the lookback."""
        now = now or time.time()
        self.db.execute("DELETE FROM fomo_positions WHERE last_ts < ?", (now - LOOKBACK_DAYS * 86400,))
        self.db.commit()
        self.smart = {
            s.wallet: s for s in self.stats(now)
            if s.closed >= MIN_CLOSED and s.win_rate >= MIN_WIN_RATE and s.pnl_usd >= MIN_PNL_USD
        }
        log.info("smart Fomo wallets: %d", len(self.smart))

    def smart_buyers(self, tracker: FomoTracker, token: str, window_sec: float = 600, now: float | None = None) -> list[WalletStats]:
        now = now or time.time()
        buyers = {t.trader for t in tracker.trades.get(token.lower(), ())
                  if t.side == "buy" and t.timestamp > now - window_sec}
        return sorted((self.smart[w] for w in buyers if w in self.smart), key=lambda s: -s.pnl_usd)

    def top(self, limit: int = 10) -> list[WalletStats]:
        return sorted(self.smart.values(), key=lambda s: -s.pnl_usd)[:limit]
