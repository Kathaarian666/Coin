"""Record mode of the rise scan (PROJE.md §3.3): score every new coin at its 3rd distinct Fomo buyer and, an hour
later, measure what buying it would have returned. Nothing is sent to Telegram from here.

Old approach ("buy, hold 1 hour"): kept only so the running bot stays unchanged until step 4 of the plan in
PROJE.md replaces it. Its trainer (scripts/scan_export.py) and cost research (scripts/rise_build.py) are in the
git history. The model is a gradient-boosting classifier kept as JSON, so the bot needs no scikit-learn.
"""

import json
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

CHECKPOINT_BUYERS = 3
DELAY = 30  # s from the checkpoint to the (virtual) entry
HOLD = 3600  # s held before the (virtual) exit
POSITION, FEE, FEE_MIN = 100.0, 0.005, 0.95
UNKNOWN_DEPTH = 3000.0  # pessimistic pool depth ($) when the recent buys cannot tell it
CAP = 100.0  # one coin's multiple is capped (bad prints)
WARMUP_BLOCKS = 6000  # coins first seen this soon after the bot started may have an older history
BLOCKS_PER_MIN = 596  # the chain makes ~9.93 blocks a second
FEATURES = ["mins_to_k", "trades_to_k", "usd_all", "usd_per_trade", "max_buy", "top_buyer_share", "repeat_buys",
            "sellers", "early_sold", "sell_usd_share", "buyers_5m", "buyers_prev5m", "usd_10m", "runup",
            "off_high", "fdv", "is_pons", "launch_age_min", "launcher_prior"]
MODEL_PATH = Path(__file__).with_name("scan_model.json")


@dataclass
class Trade:
    ts: float
    block: int
    side: int  # 1 buy, 0 sell
    trader: str
    usd: float  # 0 when unknown
    amount: int

    @property
    def price(self) -> float | None:
        return self.usd / self.amount if self.usd > 0 and self.amount > 0 else None


# --- costs (old research, scripts/rise_build.py in the git history) ---
def money_back(final: float, depth: float) -> float:
    """$ back from $100 bought at the pool price and sold at `final` x that price, after Fomo's fee (0.5%, at
    least $0.95) and slippage both ways (price step ~ trade size / pool dollar depth)."""
    fee_in = max(FEE_MIN, FEE * POSITION)
    gross = (POSITION - fee_in) / (1 + POSITION / depth) * final
    s_out = min(0.5, gross / (depth * math.sqrt(max(final, 0.05))))
    proceeds = gross * (1 - s_out)
    return proceeds - max(FEE_MIN, FEE * proceeds)


def pool_depth(trades: list[Trade], t: float) -> float:
    """Pool dollar depth from back-to-back buys (<= 60 s apart) in the 15 minutes before t, else the coin's whole
    past, else a pessimistic default: a through-origin fit of (price step) on (size of the two buys)."""
    buys = [x for x in trades if x.side == 1 and x.price and x.ts <= t]
    for since in (t - 900, -math.inf):
        sxy = sxx = 0.0
        n = 0
        for a, b in zip(buys, buys[1:]):
            if a.ts < since or b.ts - a.ts > 60:
                continue
            x, y = a.usd + b.usd, b.price / a.price - 1
            if x > 0 and abs(y) < 1:
                sxy, sxx, n = sxy + x * y, sxx + x * x, n + 1
        if n >= 5 and sxy > 0:
            return min(max(sxx / sxy, 1000.0), 1e6)
    return UNKNOWN_DEPTH


# --- features at the checkpoint (scripts/winner_study.py) ---
def checkpoint_features(trades: list[Trade], i: int, k: int, supply_raw: float | None,
                        launch: tuple[int, int] | None) -> dict | None:
    """Features at trade i, the k-th distinct buyer's (trades oldest first). `launch`: (launch block, the
    launcher's earlier launches) for a Pons coin. None if fewer than 2 priced buys so far."""
    past = trades[:i + 1]
    t = past[-1].ts
    bpx = [x.price for x in past if x.side == 1 and x.price]
    if len(bpx) < 2:
        return None
    p_now = statistics.median(bpx[-3:])
    held = [min(a, b) for a, b in zip(bpx, bpx[1:])]
    buys = [x for x in past if x.side == 1]
    b_usd = [x.usd for x in buys]
    per: dict[str, float] = {}
    for x in buys:
        per[x.trader] = per.get(x.trader, 0.0) + x.usd
    sellers = {x.trader for x in past if x.side == 0}
    first_buyers = list(dict.fromkeys(x.trader for x in buys))[:k]
    total_usd = sum(x.usd for x in past)
    return {
        "mins_to_k": (t - past[0].ts) / 60,
        "trades_to_k": len(past),
        "usd_all": sum(b_usd),
        "usd_per_trade": sum(b_usd) / len(b_usd),
        "max_buy": max(b_usd),
        "top_buyer_share": max(per.values()) / sum(per.values()) if sum(per.values()) > 0 else 1.0,
        "repeat_buys": (len(buys) - len(per)) / len(buys),
        "sellers": len(sellers),
        "early_sold": sum(w in sellers for w in first_buyers) / len(first_buyers),
        "sell_usd_share": sum(x.usd for x in past if x.side == 0) / max(1.0, total_usd),
        "buyers_5m": len({x.trader for x in buys if x.ts > t - 300}),
        "buyers_prev5m": len({x.trader for x in buys if t - 600 < x.ts <= t - 300}),
        "usd_10m": sum(x.usd for x in buys if x.ts > t - 600),
        "runup": p_now / bpx[0],
        "off_high": p_now / max(held[:max(1, len(bpx) - 1)]) if len(bpx) > 2 else 1.0,
        "fdv": p_now * supply_raw if supply_raw else math.nan,
        "is_pons": float(launch is not None),
        "launch_age_min": (past[-1].block - launch[0]) / BLOCKS_PER_MIN if launch else math.nan,
        "launcher_prior": float(launch[1]) if launch else math.nan,
    }


# --- the model ---
class ScanModel:
    """sklearn HistGradientBoostingClassifier exported to JSON: baseline + sum of trees, then a sigmoid."""

    def __init__(self, data: dict):
        self.features = data["features"]
        self.baseline = data["baseline"]
        self.trees = data["trees"]  # each: list of nodes [feature, threshold, missing_left, left, right, leaf, value]
        self.bar10, self.bar20 = data["bar10"], data["bar20"]
        self.trained_until = data.get("trained_until")

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "ScanModel | None":
        return cls(json.loads(Path(path).read_text())) if Path(path).exists() else None

    def score(self, features: dict) -> float:
        x = [features.get(f, math.nan) for f in self.features]
        raw = self.baseline
        for nodes in self.trees:
            node = nodes[0]
            while not node[5]:
                v = x[node[0]]
                go_left = node[2] if v is None or (isinstance(v, float) and math.isnan(v)) else v <= node[1]
                node = nodes[node[3] if go_left else node[4]]
            raw += node[6]
        return 1 / (1 + math.exp(-raw))


# --- the outcome an hour later ---
def entry_price(trades: list[Trade], t_in: float, depth: float) -> float | None:
    buys = [x for x in trades if x.side == 1 and x.price and x.ts <= t_in]
    if not buys:
        return None
    return statistics.median(x.price for x in buys[-3:]) * (1 + 1.5 * buys[-1].usd / depth)


def hour_result(trades: list[Trade], t_in: float, p_in: float, depth: float) -> tuple[float, float]:
    """($ result of holding $100 from t_in for an hour, highest multiple held for two buys in a row meanwhile).
    The exit is the median price of all trades in the last 10 minutes (crashes come through sells), never above
    what buys held (a lone sell print is a data error); with no trade since the entry, the entry price."""
    end = t_in + HOLD
    buys = [x.price / p_in for x in trades if x.side == 1 and x.price and t_in < x.ts <= end]
    held = [min(a, b, CAP) for a, b in zip(buys, buys[1:])]
    high = max(held, default=1.0)
    last = [x.price / p_in for x in trades if x.price and max(t_in, end - 600) < x.ts <= end]
    if last:
        final = statistics.median(last)
    else:
        after = [x.price / p_in for x in trades if x.price and t_in < x.ts <= end]
        final = after[-1] if after else 1.0
    final = min(final, max(1.0, high), CAP)
    return money_back(final, depth) - POSITION, high


@dataclass
class Coin:
    first_block: int
    first_ts: float
    eligible: bool  # its whole Fomo history was seen (first trade after the bot's warm-up)
    trades: list[Trade] = field(default_factory=list)
    buyers: set = field(default_factory=set)
    checkpoint: float | None = None


class Scanner:
    """Follows every new coin from its first Fomo trade; at the 3rd distinct buyer hands back the trade index.

    New = never traded on Fomo before, as the research defines it. Every coin the bot ever sees goes into
    `known` (kept in the database across restarts, see ScanLog); a coin seen for the first time is followed only
    if `known` has been filling for a day (a fresh install cannot tell a quiet old coin from a new one) and the
    bot's warm-up replay is over. Coins still short of 3 buyers after a day are dropped."""

    def __init__(self, known: set | None = None, known_since: float | None = None, on_new=None,
                 max_age: float = 24 * 3600, learn: float = 86400):
        self.coins: dict[str, Coin] = {}
        self.known = known if known is not None else set()
        self.known_since = known_since
        self.on_new = on_new  # called with (token, ts) for every coin seen for the first time ever
        self.start_block: int | None = None
        self.max_age = max_age
        self.learn = learn

    def _eligible(self, key: str, trade: Trade) -> bool:
        if self.known_since is None:
            self.known_since = trade.ts
        new = key not in self.known
        if new:
            self.known.add(key)
            if self.on_new:
                self.on_new(key, trade.ts)
        return (new and trade.block >= self.start_block + WARMUP_BLOCKS
                and trade.ts - self.known_since >= self.learn)

    def add(self, token: str, trade: Trade) -> int | None:
        """Adds a trade; returns its index when it is the coin's checkpoint (3rd distinct buyer), else None."""
        if self.start_block is None:
            self.start_block = trade.block
        key = token.lower()
        coin = self.coins.get(key)
        if coin is None:
            coin = self.coins[key] = Coin(trade.block, trade.ts, self._eligible(key, trade))
        if not coin.eligible:
            return None
        if coin.checkpoint is None and trade.ts - coin.first_ts > self.max_age:
            coin.eligible, coin.trades, coin.buyers = False, [], set()
            return None
        coin.trades.append(trade)
        if trade.side == 1 and trade.trader not in coin.buyers and coin.checkpoint is None:
            coin.buyers.add(trade.trader)
            if len(coin.buyers) == CHECKPOINT_BUYERS:
                coin.checkpoint = trade.ts
                return len(coin.trades) - 1
        return None

    def prune(self, now: float | None = None):
        """Drops the trades of coins whose hour has been read, and of coins short of 3 buyers after a day."""
        now = now or time.time()
        for key, c in list(self.coins.items()):
            if c.checkpoint is not None and now - c.checkpoint > DELAY + HOLD + 1800:
                del self.coins[key]
            elif c.checkpoint is None and c.eligible and now - c.first_ts > self.max_age:
                del self.coins[key]
            elif not c.eligible and now - c.first_ts > 7 * 86400:
                del self.coins[key]  # forget old coins' markers after a week


class ScanLog:
    """The record: one row per scored coin; `result` is filled an hour later (NULL if it could not be read)."""

    SCHEMA = """CREATE TABLE IF NOT EXISTS scan_log (token TEXT PRIMARY KEY, ts REAL NOT NULL, score REAL NOT NULL,
                bar10 REAL, bar20 REAL, features TEXT, depth REAL, p_in REAL, result REAL, high REAL,
                done INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS scan_known (token TEXT PRIMARY KEY, ts REAL NOT NULL);"""

    def __init__(self, db):
        self.db = db
        self.db.executescript(self.SCHEMA)
        self.db.commit()

    def known(self) -> tuple[set, float | None]:
        """Every coin the bot has seen on Fomo, and since when it has been keeping them."""
        since = self.db.execute("SELECT MIN(ts) FROM scan_known").fetchone()[0]
        return {t for (t,) in self.db.execute("SELECT token FROM scan_known")}, since

    def remember(self, token: str, ts: float):
        self.db.execute("INSERT OR IGNORE INTO scan_known VALUES (?, ?)", (token, ts))
        self._pending = getattr(self, "_pending", 0) + 1
        if self._pending >= 50:
            self.db.commit()
            self._pending = 0

    def bars(self, model: ScanModel, now: float, min_rows: int = 100) -> tuple[float, float]:
        """Top-10% / top-20% bars: percentiles of the last 2 days' scores once there are enough, else the model's."""
        scores = sorted(s for (s,) in self.db.execute("SELECT score FROM scan_log WHERE ts >= ?", (now - 2 * 86400,)))
        if len(scores) < min_rows:
            return model.bar10, model.bar20
        pick = lambda q: scores[min(len(scores) - 1, int(q * len(scores)))]  # noqa: E731
        return pick(0.9), pick(0.8)

    def add(self, token: str, ts: float, score: float, bar10: float, bar20: float, features: dict):
        self.db.execute("INSERT OR IGNORE INTO scan_log (token, ts, score, bar10, bar20, features) VALUES (?, ?, ?, ?, ?, ?)",
                        (token.lower(), ts, score, bar10, bar20,
                         json.dumps({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in features.items()})))
        self.db.commit()

    def due(self, now: float) -> list[tuple[str, float]]:
        return self.db.execute("SELECT token, ts FROM scan_log WHERE done = 0 AND ts <= ?",
                               (now - DELAY - HOLD - 60,)).fetchall()

    def close(self, token: str, depth=None, p_in=None, result=None, high=None):
        self.db.execute("UPDATE scan_log SET depth = ?, p_in = ?, result = ?, high = ?, done = 1 WHERE token = ?",
                        (depth, p_in, result, high, token.lower()))
        self.db.commit()

    def rows(self, since: float) -> list[dict]:
        cur = self.db.execute("SELECT token, ts, score, bar10, bar20, result, high, done FROM scan_log WHERE ts >= ? "
                              "ORDER BY ts", (since,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def evaluate(trades: list[Trade], ts: float) -> tuple[float, float, float, float] | None:
    """(depth, entry price, $ result, high) of the virtual trade on a checkpoint at ts; None without an entry."""
    depth = pool_depth(trades, ts)
    p_in = entry_price(trades, ts + DELAY, depth)
    if not p_in:
        return None
    result, high = hour_result(trades, ts + DELAY, p_in, depth)
    return depth, p_in, result, high


def summary(rows: list[dict]) -> dict:
    """Counts and results of the record for the top 10%, the top 20% and every scored coin."""
    out = {"scored": len(rows), "measured": sum(1 for r in rows if r["result"] is not None),
           "pending": sum(1 for r in rows if not r["done"]),
           "unmeasured": sum(1 for r in rows if r["done"] and r["result"] is None)}
    for name, keep in (("top10", lambda r: r["score"] >= r["bar10"]), ("top20", lambda r: r["score"] >= r["bar20"]),
                       ("all", lambda r: True)):
        v = sorted(r["result"] for r in rows if keep(r) and r["result"] is not None)
        out[name] = {"n": len(v), "pending": sum(1 for r in rows if keep(r) and not r["done"]),
                     "mean": sum(v) / len(v) if v else None, "median": statistics.median(v) if v else None,
                     "win": sum(x > 0 for x in v) / len(v) if v else None, "total": sum(v), "best": v[-1] if v else None}
    return out
