"""Paper test of the alert rule (PROJE.md §2 step 4/5): live, nothing is bought or sent unless asked.

Every new coin (never traded on Fomo before) is followed from its first Fomo trade. At its 5th distinct Fomo buyer
the research features are computed (scripts/winner_study.py, same formulas), the 2x model scores them and a coin
in the top 2 % of the last 2 days' scores is an alert. Each alert opens a virtual trade with the user's rules
(scripts/trade_sim.py): bought 30 s later at the last price then, half sold when the bot's "2x" comes (two buys in
a row at >= 2x the alert price), the rest sold once two trades in a row are at <= half of the highest price held
(two buys), everything sold at -50 % before a 2x; Fomo's fee and price impact included. /karne reads the record.

The first 3 buyers' track record (`buyers_hit_rate`) is the share of their earlier coins that made a 2x within an
hour of the 5th-buyer moment; the book starts from the research data (paper_book.json) and grows live.
"""

import bisect
import json
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

CHECKPOINT_BUYERS = 5
DELAY = 30  # s: the user's reaction time
FEE, FEE_MIN = 0.005, 0.95
CAP = 100.0  # a coin's price multiple is capped (bad prints)
DEAD = 6 * 3600  # no trade for this long: the coin is valued at half its last price
MAX_HOLD = 3 * 86400  # a paper trade still open after this is closed at the last price
FOLLOW = 26 * 3600  # a coin short of 5 buyers after this is dropped
WARMUP_BLOCKS = 6000  # coins first seen this soon after the bot started may have an older history
BLOCKS_PER_S = 9.93
TOP = 0.02  # alert share
BANKROLL = 1000.0
MODEL_PATH = Path(__file__).with_name("paper_model.json")
BOOK_PATH = Path(__file__).with_name("paper_book.json")


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


# --- features at the alert moment (scripts/winner_study.py, security_extra.depth_at) ---
def depth_at(bpx: list[float], busd: list[float], bts: list[float], t: float) -> float:
    est = []
    p_prev = None
    for p, x, ts in zip(bpx, busd, bts):
        if t - 900 <= ts <= t:
            if p_prev is not None and p_prev > 0:
                r = p / p_prev
                if 1.001 < r < 3 and x > 0:
                    est.append(x / (math.sqrt(r) - 1))
            p_prev = p
    return statistics.median(est) if len(est) >= 2 else math.nan


def alert_features(trades: list[Trade], i: int, k: int, supply_raw: float | None, launch_ts: float | None,
                   buyers_hit_rate: float) -> dict | None:
    """Features at trade i, the k-th distinct buyer's (trades oldest first); None without 2 priced buys."""
    t = trades[i].ts
    past = trades[:i + 1]
    priced = [x for x in trades if x.side == 1 and x.price and x.ts <= t]  # winner_study: buys up to now
    if len(priced) < 2:
        return None
    bpx = [x.price for x in priced]
    p_now = bpx[-1]
    held = [min(a, b) for a, b in zip(bpx, bpx[1:])]
    buys = [x for x in past if x.side == 1]
    b_usd = [x.usd for x in buys]
    sellers = {x.trader for x in past if x.side == 0}
    first_buyers = list(dict.fromkeys(x.trader for x in buys))[:k]
    total = sum(x.usd for x in past)
    last_min = [x for x in buys if x.ts > t - 60]
    blocks = [x.block for x in buys]
    return {
        "mins_to_k": (t - past[0].ts) / 60,
        "trades_to_k": len(past),
        "usd_all": sum(b_usd),
        "usd_per_trade": sum(b_usd) / len(b_usd),
        "max_buy": max(b_usd),
        "sellers": len(sellers),
        "early_sold": sum(w in sellers for w in first_buyers) / len(first_buyers),
        "sell_usd_share": sum(x.usd for x in past if x.side == 0) / max(1.0, total),
        "buyers_5m": len({x.trader for x in buys if x.ts > t - 300}),
        "usd_10m": sum(x.usd for x in buys if x.ts > t - 600),
        "runup": p_now / bpx[0],
        "off_high": p_now / max(held[:max(1, len(bpx) - 1)]) if len(bpx) > 2 else 1.0,
        "fdv": p_now * supply_raw if supply_raw else math.nan,
        "launch_age_min": (t - launch_ts) / 60 if launch_ts else math.nan,
        "depth_usd": depth_at(bpx, [x.usd for x in priced], [x.ts for x in priced], t),
        "buyers_60s": len({x.trader for x in last_min}),
        "usd_60s_share": sum(x.usd for x in last_min) / max(1.0, sum(b_usd)),
        "same_block_buys": sum(1 for b in blocks if blocks.count(b) > 1),
        "small_buy_share": sum(1 for u in b_usd if u < 20) / len(b_usd),
        "buyers_hit_rate": buyers_hit_rate,
    }


class Model:
    """sklearn HistGradientBoostingClassifier exported to JSON (scripts/paper_export.py): sum of trees, sigmoid."""

    def __init__(self, data: dict):
        self.features = data["features"]
        self.baseline = data["baseline"]
        self.trees = data["trees"]  # each: list of nodes [feature, threshold, missing_left, left, right, leaf, value]
        self.bar = data["bar"]  # starting top-2 % bar, until the bot has its own 2 days of scores
        self.trained_until = data.get("trained_until")

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "Model | None":
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


# --- the virtual trade (scripts/trade_sim.py path_events, rule "iz") ---
def _two_in_row(values, cond) -> int | None:
    prev = False
    for j, v in enumerate(values):
        ok = cond(v)
        if ok and prev:
            return j
        prev = ok
    return None


def paper_trade(trades: list[Trade], t_alert: float, now: float) -> dict | None:
    """The user's trade on an alert at t_alert, as far as it is known at `now`: entry, closed legs
    [(time, share, price)], 'open' share and kind ('2x' / 'stop' / 'yok'). None before the entry is known."""
    p_alert = next((x.price for x in reversed(trades) if x.side == 1 and x.price and x.ts <= t_alert), None)
    t_in = t_alert + DELAY
    if p_alert is None or now < t_in:
        return None
    p_in = next((x.price for x in reversed(trades) if x.side == 1 and x.price and x.ts <= t_in), p_alert)
    after = [x for x in trades if t_in < x.ts <= now and x.price]
    px = [min(x.price, CAP * p_alert) for x in after]
    buys = [(x.ts, p) for x, p in zip(after, px) if x.side == 1]
    j = _two_in_row([p for _, p in buys], lambda p: p >= 2 * p_alert)
    t2x = buys[j][0] if j is not None else math.inf
    k = _two_in_row(px, lambda p: p <= 0.5 * p_in)
    tstop = after[k].ts if k is not None else math.inf
    out = {"p_alert": p_alert, "t_in": t_in, "p_in": p_in, "legs": [], "open": 1.0, "kind": "yok"}
    if tstop < t2x:
        out.update(legs=[(tstop, 1.0, px[k])], open=0.0, kind="stop")
        return out
    if not math.isfinite(t2x):
        return out
    out.update(legs=[(t2x, 0.5, 2 * p_alert)], open=0.5, kind="2x")
    peak, prev_buy, below = 2 * p_alert, None, 0
    for x, p in zip(after, px):
        if x.ts <= t2x:
            continue
        if x.side == 1:
            if prev_buy is not None:
                peak = max(peak, min(prev_buy, p))
            prev_buy = p
        below = below + 1 if p <= 0.5 * peak else 0
        if below == 2:
            out["legs"].append((x.ts, 0.5, p))
            out["open"] = 0.0
            break
    return out


def last_value(trades: list[Trade], now: float, p_ref: float) -> float:
    """Median of the last 5 prices (broken sell prints), half for a dead coin."""
    priced = [x for x in trades if x.price and x.ts <= now]
    if not priced:
        return p_ref
    p = statistics.median(x.price for x in priced[-5:])
    return min(p, CAP * p_ref) / (2 if now - priced[-1].ts > DEAD else 1)


def net_return(trade: dict, depth: float, stake: float, value_open: float | None = None) -> float:
    """Return on `stake` after the fee both ways and price impact; open share valued at value_open."""
    fee = max(FEE_MIN, FEE * stake)
    coins = (stake - fee) / (trade["p_in"] * (1 + stake / depth))
    total = 0.0
    legs = list(trade["legs"])
    if trade["open"] and value_open is not None:
        legs.append((None, trade["open"], value_open))
    for _, share, price in legs:
        v = coins * share * price
        v *= max(0.0, 1 - v / depth)
        total += max(0.0, v - max(FEE_MIN, FEE * v))
    return total / stake - 1


# --- following new coins ---
@dataclass
class Coin:
    first_ts: float
    eligible: bool
    trades: list[Trade] = field(default_factory=list)
    buyers: list = field(default_factory=list)
    moment: float | None = None
    keep_until: float = 0.0  # trades are kept this long (book outcome, paper trade)


class Follower:
    """New coins from their first Fomo trade; reports the 5th distinct buyer's trade index (once per coin).

    New = never traded on Fomo before (research definition). Every coin seen goes into `known`, kept across
    restarts; a coin seen for the first time is followed only once `known` has been filling for a day and the
    warm-up replay is over."""

    def __init__(self, known: set | None = None, known_since: float | None = None, on_new=None, learn: float = 86400):
        self.coins: dict[str, Coin] = {}
        self.known = known if known is not None else set()
        self.known_since = known_since
        self.on_new = on_new
        self.start_block: int | None = None
        self.learn = learn

    def _eligible(self, key: str, trade: Trade) -> bool:
        if self.known_since is None:
            self.known_since = trade.ts
        new = key not in self.known
        if new:
            self.known.add(key)
            if self.on_new:
                self.on_new(key, trade.ts)
        return new and trade.block >= self.start_block + WARMUP_BLOCKS and trade.ts - self.known_since >= self.learn

    def add(self, token: str, trade: Trade) -> int | None:
        if self.start_block is None:
            self.start_block = trade.block
        key = token.lower()
        coin = self.coins.get(key)
        if coin is None:
            coin = self.coins[key] = Coin(trade.ts, self._eligible(key, trade))
        if not coin.eligible:
            return None
        coin.trades.append(trade)
        if trade.side == 1 and coin.moment is None and trade.trader not in coin.buyers:
            coin.buyers.append(trade.trader)
            if len(coin.buyers) == CHECKPOINT_BUYERS:
                coin.moment = trade.ts
                coin.keep_until = trade.ts + 3600 + 60  # at least until the book outcome is known
                return len(coin.trades) - 1
        return None

    def prune(self, now: float):
        for key, c in list(self.coins.items()):
            if not c.eligible:
                if now - c.first_ts > 7 * 86400:
                    del self.coins[key]  # forget old coins' markers after a week (they stay in `known`)
            elif c.moment is None and now - c.first_ts > FOLLOW:
                del self.coins[key]
            elif c.moment is not None and now > c.keep_until:
                del self.coins[key]


class Book:
    """First buyers' record: wallet -> [coins, coins with a 2x within an hour of the 5th-buyer moment]."""

    def __init__(self, db, seed: Path = BOOK_PATH):
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS paper_book (wallet TEXT PRIMARY KEY, n INTEGER, hits INTEGER)")
        if not db.execute("SELECT 1 FROM paper_book LIMIT 1").fetchone() and Path(seed).exists():
            rows = json.loads(Path(seed).read_text())
            db.executemany("INSERT OR REPLACE INTO paper_book VALUES (?, ?, ?)",
                           [(w.lower(), n, h) for w, (n, h) in rows.items()])
        db.execute("""CREATE TABLE IF NOT EXISTS paper_pending (token TEXT PRIMARY KEY, ts REAL, p REAL,
                      wallets TEXT)""")
        db.commit()

    def rate(self, wallets: list[str]) -> float:
        n = hits = 0
        for w in wallets:
            row = self.db.execute("SELECT n, hits FROM paper_book WHERE wallet = ?", (w.lower(),)).fetchone()
            if row:
                n, hits = n + row[0], hits + row[1]
        return hits / n if n >= 3 else math.nan

    def watch(self, token: str, ts: float, price: float, wallets: list[str]):
        self.db.execute("INSERT OR IGNORE INTO paper_pending VALUES (?, ?, ?, ?)",
                        (token.lower(), ts, price, ",".join(w.lower() for w in wallets)))
        self.db.commit()

    def settle(self, follower: Follower, now: float):
        """An hour after a 5th-buyer moment: did two buys in a row reach 2x? Then the first buyers' record grows."""
        for token, ts, p, wallets in self.db.execute("SELECT token, ts, p, wallets FROM paper_pending WHERE ts <= ?",
                                                     (now - 3600,)).fetchall():
            coin = follower.coins.get(token)
            if coin is not None:
                buys = [x.price for x in coin.trades if x.side == 1 and x.price and ts < x.ts <= ts + 3600]
                hit = _two_in_row(buys, lambda v: v >= 2 * p) is not None
                for w in wallets.split(","):
                    if w:
                        self.db.execute("""INSERT INTO paper_book VALUES (?, 1, ?) ON CONFLICT(wallet)
                                           DO UPDATE SET n = n + 1, hits = hits + excluded.hits""", (w, int(hit)))
            self.db.execute("DELETE FROM paper_pending WHERE token = ?", (token,))
        self.db.commit()


class PaperLog:
    """One row per scored coin; alerts carry a virtual trade that is updated until it closes."""

    SCHEMA = """CREATE TABLE IF NOT EXISTS paper_log (token TEXT PRIMARY KEY, ts REAL NOT NULL, score REAL NOT NULL,
                bar REAL, alert INTEGER NOT NULL DEFAULT 0, size REAL, features TEXT, seen REAL, depth REAL,
                p_alert REAL, p_in REAL, kind TEXT, ret REAL, closed INTEGER NOT NULL DEFAULT 0, closed_ts REAL);
                CREATE TABLE IF NOT EXISTS scan_known (token TEXT PRIMARY KEY, ts REAL NOT NULL);"""

    def __init__(self, db):
        self.db = db
        db.executescript(self.SCHEMA)
        db.commit()
        self._pending = 0

    def known(self) -> tuple[set, float | None]:
        since = self.db.execute("SELECT MIN(ts) FROM scan_known").fetchone()[0]
        return {t for (t,) in self.db.execute("SELECT token FROM scan_known")}, since

    def remember(self, token: str, ts: float):
        self.db.execute("INSERT OR IGNORE INTO scan_known VALUES (?, ?)", (token, ts))
        self._pending += 1
        if self._pending >= 50:
            self.db.commit()
            self._pending = 0

    def bar(self, model: Model, now: float, min_rows: int = 300) -> float:
        """Top-2 % bar: the last 2 days' scores once there are enough, else the model's starting bar."""
        scores = sorted(s for (s,) in self.db.execute("SELECT score FROM paper_log WHERE ts >= ?", (now - 2 * 86400,)))
        if len(scores) < min_rows:
            return model.bar
        return scores[min(len(scores) - 1, int((1 - TOP) * len(scores)))]

    def percentile(self, score: float, now: float) -> float:
        scores = sorted(s for (s,) in self.db.execute("SELECT score FROM paper_log WHERE ts >= ?", (now - 2 * 86400,)))
        return bisect.bisect_left(scores, score) / len(scores) if scores else 1.0

    def add(self, token: str, ts: float, score: float, bar: float, alert: bool, size: float | None, features: dict,
            seen: float, depth: float | None):
        clean = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in features.items()}
        self.db.execute("""INSERT OR IGNORE INTO paper_log (token, ts, score, bar, alert, size, features, seen, depth)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (token.lower(), ts, score, bar, int(alert), size, json.dumps(clean), seen, depth))
        self.db.commit()

    def open_alerts(self) -> list[tuple]:
        return self.db.execute("SELECT token, ts, depth FROM paper_log WHERE alert = 1 AND closed = 0").fetchall()

    def update(self, token: str, trade: dict | None, ret: float | None, closed: bool, now: float):
        if trade is None:
            self.db.execute("UPDATE paper_log SET closed = ?, closed_ts = ? WHERE token = ?",
                            (int(closed), now if closed else None, token))
        else:
            self.db.execute("""UPDATE paper_log SET p_alert = ?, p_in = ?, kind = ?, ret = ?, closed = ?, closed_ts = ?
                               WHERE token = ?""", (trade["p_alert"], trade["p_in"], trade["kind"], ret, int(closed),
                                                    now if closed else None, token))
        self.db.commit()

    def alerts(self, since: float) -> list[dict]:
        cur = self.db.execute("""SELECT token, ts, score, size, seen, kind, ret, closed FROM paper_log
                                 WHERE alert = 1 AND ts >= ? ORDER BY ts""", (since,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def scored(self, since: float) -> int:
        return self.db.execute("SELECT COUNT(*) FROM paper_log WHERE ts >= ?", (since,)).fetchone()[0]


def size_for(pct: float) -> float:
    """Bankroll share by rank inside the top 2 % (PROJE.md §1: 4 / 2 / 1 %)."""
    return 0.04 if pct >= 1 - TOP / 3 else 0.02 if pct >= 1 - 2 * TOP / 3 else 0.01


def bankroll(rows: list[dict]) -> float:
    """$1000 run through the alerts in time order with their sizes and net returns (closed or marked)."""
    bank = BANKROLL
    for r in rows:
        if r["ret"] is not None:
            bank += bank * (r["size"] or 0.01) * r["ret"]
    return bank


def summary(rows: list[dict], scored: int) -> dict:
    done = [r for r in rows if r["ret"] is not None]
    rets = [r["ret"] for r in done]
    lat = [r["seen"] - r["ts"] for r in rows if r["seen"]]
    return {
        "scored": scored, "alerts": len(rows), "closed": sum(1 for r in rows if r["closed"]),
        "x2": sum(1 for r in rows if r["kind"] == "2x"), "stop": sum(1 for r in rows if r["kind"] == "stop"),
        "mean": sum(rets) / len(rets) if rets else None, "median": statistics.median(rets) if rets else None,
        "win": sum(x > 0 for x in rets) / len(rets) if rets else None,
        "bank": bankroll(rows), "latency": statistics.median(lat) if lat else None,
    }


def now_ts() -> float:
    return time.time()
