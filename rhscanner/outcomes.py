"""Outcome log: what happened to every signal, so the filters can be measured.

The kinds of signals tracked, each at most once per token:
  alert     analysed and sent to Telegram
  filtered  analysed but held back (trust or momentum score below the minimum)
  shadow    crossed a lower bar of Fomo buying and was never analysed: the
            baseline the alerts have to beat
  pons      a Pons coin buying up on its bonding curve before graduation
  pons_junk the same, dropped by the obvious-junk filter (pons.junk_reasons)
  pons_early / pons_early_junk   the same at a lower (earlier) buying bar
  exit / caution  a 🔴 ÇIK / 🟠 DİKKAT sent after an alert (priced from that moment)

For each, price and liquidity are sampled from DexScreener at fixed minutes
after the signal (0, 5, 10 ... 1440), in batches of up to 30 tokens per call.
Coins DexScreener does not list yet (Pons curves) are priced by `price_fn`.
"""

import json
import logging
import statistics
import time
from collections import defaultdict

from .momentum import tuned_points
from .rugrisk import rug_risk

log = logging.getLogger(__name__)

CHECKPOINTS_MIN = [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360, 720, 1440]
BATCH = 30
LATE_WINDOW = 86400  # a first sighting older than this belongs to an earlier wave

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    trust INTEGER,
    momentum INTEGER,
    features TEXT,
    pair TEXT,
    next_idx INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    UNIQUE (token, kind)
);
CREATE TABLE IF NOT EXISTS samples (
    signal_id INTEGER NOT NULL,
    minute INTEGER NOT NULL,
    ts REAL NOT NULL,
    price REAL,
    liquidity REAL,
    PRIMARY KEY (signal_id, minute)
);
CREATE INDEX IF NOT EXISTS signals_pending ON signals (done, ts);
"""


def pick_pair(pairs: list[dict], token: str, pair_address: str | None) -> dict | None:
    """The stored pool if DexScreener still lists it, else the token's deepest pool."""
    own = [p for p in pairs if (p.get("baseToken") or {}).get("address", "").lower() == token.lower()]
    if pair_address:
        for p in own:
            if (p.get("pairAddress") or "").lower() == pair_address.lower():
                return p
    return max(own, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, default=None)


class OutcomeLog:
    def __init__(self, db):
        self.db = db
        self.db.executescript(SCHEMA)
        self.db.commit()

    def record(self, token: str, kind: str, trust: int | None = None, momentum: int | None = None,
               features: dict | None = None, pair: str | None = None, ts: float | None = None) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO signals (token, ts, kind, trust, momentum, features, pair) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token.lower(), ts or time.time(), kind, trust, momentum, json.dumps(features or {}, default=str), pair),
        )
        self.db.commit()
        return cur.rowcount == 1

    def record_history(self, token: str, kind: str, ts: float, features: dict,
                       samples: dict[int, float | None], now: float) -> bool:
        """A signal replayed from the past, with the price samples already known (minute -> price).

        Sampling carries on live from the first checkpoint that is still in the future."""
        if not self.record(token, kind, features=features, ts=ts):
            return False
        (signal_id,) = self.db.execute(
            "SELECT id FROM signals WHERE token = ? AND kind = ?", (token.lower(), kind)
        ).fetchone()
        self.db.executemany(
            "INSERT OR REPLACE INTO samples (signal_id, minute, ts, price, liquidity) VALUES (?, ?, ?, ?, NULL)",
            [(signal_id, minute, ts + minute * 60, price) for minute, price in samples.items()],
        )
        next_idx = next((i for i, m in enumerate(CHECKPOINTS_MIN) if ts + m * 60 > now), len(CHECKPOINTS_MIN))
        self.db.execute("UPDATE signals SET next_idx = ?, done = ? WHERE id = ?",
                        (next_idx, int(next_idx >= len(CHECKPOINTS_MIN)), signal_id))
        self.db.commit()
        return True

    def alert_paths(self, hours: float, now: float | None = None) -> list[tuple[list[tuple[int, float]], int | None]]:
        """Price paths of alerts at least a day old (price / price at the alert, per checkpoint minute),
        each with the minute of its 🔴 ÇIK if one was sent."""
        now = now or time.time()
        rows = self.db.execute(
            "SELECT id, token, ts FROM signals WHERE kind = 'alert' AND ts >= ? AND ts <= ?",
            (now - hours * 3600, now - 86400),
        ).fetchall()
        exits = dict(self.db.execute("SELECT token, ts FROM signals WHERE kind = 'exit'").fetchall())
        paths = []
        for signal_id, token, ts in rows:
            priced = [(m, p) for m, p in self.db.execute(
                "SELECT minute, price FROM samples WHERE signal_id = ? AND price > 0 ORDER BY minute", (signal_id,))]
            if not priced or priced[0][0] != 0:
                continue
            exit_min = int((exits[token] - ts) / 60) if token in exits and exits[token] >= ts else None
            paths.append(([(m, p / priced[0][1]) for m, p in priced], exit_min))
        return paths

    def unmeasured(self, hours: float, now: float | None = None) -> dict[str, int]:
        """Signals at least an hour old, per kind, left out of /karne for want of a price at the signal."""
        now = now or time.time()
        rows = self.db.execute(
            "SELECT s.kind, COUNT(*) FROM signals s LEFT JOIN samples m ON m.signal_id = s.id AND m.minute = 0 "
            "WHERE s.ts >= ? AND s.ts <= ? AND (m.price IS NULL OR m.price <= 0) GROUP BY s.kind",
            (now - hours * 3600, now - 3600),
        ).fetchall()
        return dict(rows)

    def signals_for(self, token: str, kinds: tuple[str, ...]) -> list[dict]:
        """A token's signals of the given kinds, oldest first, with the price at the signal (p0)."""
        marks = ",".join("?" * len(kinds))
        rows = self.db.execute(
            f"SELECT s.id, s.ts, s.kind, s.trust, s.momentum, s.features, m.price FROM signals s "
            f"LEFT JOIN samples m ON m.signal_id = s.id AND m.minute = 0 "
            f"WHERE s.token = ? AND s.kind IN ({marks}) ORDER BY s.ts", (token.lower(), *kinds),
        ).fetchall()
        return [{"ts": ts, "kind": kind, "trust": trust, "momentum": momentum, "p0": price,
                 "features": json.loads(features or "{}")}
                for _, ts, kind, trust, momentum, features, price in rows]

    def due(self, now: float) -> list[tuple]:
        rows = self.db.execute(
            "SELECT id, token, ts, next_idx, pair, momentum, features FROM signals WHERE done = 0"
        ).fetchall()
        return [r for r in rows if r[2] + CHECKPOINTS_MIN[r[3]] * 60 <= now]

    async def tick(self, dexscreener, momentum_fn=None, now: float | None = None, price_fn=None) -> int:
        """Take every sample that is due; returns how many were written."""
        now = now or time.time()
        rows = self.due(now)
        if not rows:
            return 0
        tokens = sorted({r[1] for r in rows})
        pairs_by_token: dict[str, list[dict]] = defaultdict(list)
        for i in range(0, len(tokens), BATCH):
            for pair in await dexscreener.tokens(tokens[i: i + BATCH]):
                pairs_by_token[(pair.get("baseToken") or {}).get("address", "").lower()].append(pair)

        written = 0
        for signal_id, token, ts, next_idx, pair_address, momentum, features in rows:
            elapsed_min = (now - ts) / 60
            # After downtime, record one sample at the latest checkpoint that is due.
            idx = next_idx
            while idx + 1 < len(CHECKPOINTS_MIN) and CHECKPOINTS_MIN[idx + 1] <= elapsed_min:
                idx += 1
            pairs = pairs_by_token.get(token, [])
            pair = pick_pair(pairs, token, pair_address)
            price = float(pair["priceUsd"]) if pair and pair.get("priceUsd") else None
            liquidity = (pair.get("liquidity") or {}).get("usd") if pair else None
            if price is None and price_fn:
                price = price_fn(token)  # USD, from the bonding curve; no liquidity figure
            self.db.execute(
                "INSERT OR REPLACE INTO samples (signal_id, minute, ts, price, liquidity) VALUES (?, ?, ?, ?, ?)",
                (signal_id, CHECKPOINTS_MIN[idx], now, price, liquidity),
            )
            updates = {"next_idx": idx + 1, "done": int(idx + 1 >= len(CHECKPOINTS_MIN))}
            if pair and not pair_address:
                updates["pair"] = pair.get("pairAddress")
            if momentum is None and momentum_fn and pairs and idx == 0:
                # Shadow signals are scored here, from the same data an alert would have seen; momentum_fn may
                # also return market features (FDV, liquidity, age...) to keep with the signal.
                stored = json.loads(features or "{}")
                result = momentum_fn(stored, pairs, updates.get("pair") or pair_address)
                score, extra = result if isinstance(result, tuple) else (result, None)
                updates["momentum"] = score
                if extra:
                    updates["features"] = json.dumps({**stored, **extra}, default=str)
            sets = ", ".join(f"{k} = ?" for k in updates)
            self.db.execute(f"UPDATE signals SET {sets} WHERE id = ?", (*updates.values(), signal_id))
            written += 1
        self.db.commit()
        return written

    def first_sighting(self, token: str) -> tuple[float, float | None] | None:
        """When the coin was first seen (its earliest shadow / filtered / alert signal) and the price then."""
        row = self.db.execute(
            "SELECT s.ts, m.price FROM signals s LEFT JOIN samples m ON m.signal_id = s.id AND m.minute = 0 "
            "WHERE s.token = ? AND s.kind IN ('shadow', 'filtered', 'alert') ORDER BY s.ts LIMIT 1", (token.lower(),)
        ).fetchone()
        return (row[0], row[1]) if row else None

    # --- evaluation ---
    def results(self, hours: float, now: float | None = None) -> list[dict]:
        """Per-signal outcome metrics for signals at least an hour old, from the last `hours`."""
        now = now or time.time()
        rows = self.db.execute(
            "SELECT id, token, ts, kind, trust, momentum, features FROM signals WHERE ts >= ? AND ts <= ?",
            (now - hours * 3600, now - 3600),
        ).fetchall()
        out = []
        for signal_id, token, ts, kind, trust, momentum, features in rows:
            samples = self.db.execute(
                "SELECT minute, price, liquidity FROM samples WHERE signal_id = ? ORDER BY minute", (signal_id,)
            ).fetchall()
            base = next((s for s in samples if s[0] == 0 and s[1]), None)
            if not base:
                continue
            p0, l0 = base[1], base[2]
            priced = [(m, p, liq) for m, p, liq in samples if p]
            within = lambda limit: [p / p0 for m, p, _ in priced if m <= limit]  # noqa: E731
            day = within(1440)
            at60 = next((p / p0 for m, p, _ in priced if m == 60), None)
            last_m, last_p, last_l = priced[-1]
            rugged = last_p / p0 <= 0.1 or (l0 and last_l is not None and last_l / l0 <= 0.2)
            out.append({
                "token": token, "kind": kind, "trust": trust, "momentum": momentum,
                "max_60": max(within(60), default=None),
                "max_all": max(day, default=None),
                # a level held over two samples in a row: one trade on a shallow pool can print a spike
                "held_all": max((min(a, b) for a, b in zip(day, day[1:])), default=None),
                "ret_60": at60,
                "last_min": last_m,
                "rugged": bool(rugged),
                "findings": (feats := json.loads(features or "{}")).get("findings") or [],
                "features": feats,
                "p0": p0,
                "ts": ts,
                "path": [(m, p / p0) for m, p, _ in priced],
            })
        self._attach_lateness(out)
        return out

    def _attach_lateness(self, results: list[dict]):
        """How late each analysed signal came: its price against the coin's first sighting (the shadow signal at
        half the buyer bar) within the day before, kept in features as runup_first / since_first_min.
        first_seen says where that starting point came from: "self" (no earlier signal: the alert was the first
        sighting), "old" (the earlier sighting is over a day old: an earlier wave; one signal per token and kind),
        "unpriced" (earlier sighting without a price) or "shadow" (measured)."""
        first: dict[str, tuple[float, float | None]] = {}
        for token, ts, price in self.db.execute(
            "SELECT s.token, s.ts, m.price FROM signals s LEFT JOIN samples m ON m.signal_id = s.id AND m.minute = 0 "
            "WHERE s.kind IN ('shadow', 'filtered', 'alert') ORDER BY s.ts"
        ):
            first.setdefault(token, (ts, price))
        for r in results:
            if r["kind"] not in ("alert", "filtered"):
                continue
            first_ts, first_price = first.get(r["token"], (r["ts"], r["p0"]))
            extra = {}
            if first_ts >= r["ts"]:
                extra = {"first_seen": "self", "runup_first": 1.0, "since_first_min": 0.0}
            elif r["ts"] - first_ts > LATE_WINDOW:
                extra = {"first_seen": "old"}
            elif not first_price or first_price <= 0:
                extra = {"first_seen": "unpriced"}
            else:
                extra = {"first_seen": "shadow", "runup_first": round(r["p0"] / first_price, 3),
                         "since_first_min": round((r["ts"] - first_ts) / 60, 1)}
            r["features"] = {**r["features"], **extra}


def summarize(results: list[dict]) -> dict:
    """Hit rates for a group of results."""
    if not results:
        return {"n": 0}
    n = len(results)
    rate = lambda cond: round(100.0 * sum(1 for r in results if cond(r)) / n, 1)  # noqa: E731
    max60 = [r["max_60"] for r in results if r["max_60"] is not None]
    ret60 = [r["ret_60"] for r in results if r["ret_60"] is not None]
    return {
        "n": n,
        "x2_60": rate(lambda r: (r["max_60"] or 0) >= 2),
        "x2_all": rate(lambda r: (r["max_all"] or 0) >= 2),
        "x5_all": rate(lambda r: (r["max_all"] or 0) >= 5),
        "x5_held": rate(lambda r: (r.get("held_all") or 0) >= 5),
        "up50_60": rate(lambda r: (r["max_60"] or 0) >= 1.5),
        "down50_60": rate(lambda r: r["ret_60"] is not None and r["ret_60"] <= 0.5),
        "rugged": rate(lambda r: r["rugged"]),
        "median_max60": round(statistics.median(max60), 2) if max60 else None,
        "median_ret60": round(statistics.median(ret60), 2) if ret60 else None,
    }


def summarize_exits(results: list[dict]) -> dict:
    """Whether exit signals were right: prices are relative to the moment the signal was sent."""
    if not results:
        return {"n": 0}
    n = len(results)
    rate = lambda cond: round(100.0 * sum(1 for r in results if cond(r)) / n, 1)  # noqa: E731
    ret60 = [r["ret_60"] for r in results if r["ret_60"] is not None]
    return {
        "n": n,
        "lower_60": rate(lambda r: r["ret_60"] is not None and r["ret_60"] < 1),
        "down20_60": rate(lambda r: r["ret_60"] is not None and r["ret_60"] <= 0.8),
        "up50_60": rate(lambda r: (r["max_60"] or 0) >= 1.5),
        "x2_all": rate(lambda r: (r["max_all"] or 0) >= 2),
        "rugged": rate(lambda r: r["rugged"]),
        "median_ret60": round(statistics.median(ret60), 2) if ret60 else None,
    }


def momentum_bucket(score: int | None) -> str:
    if score is None:
        return "?"
    return "🚀 70+" if score >= 70 else "🟡 45-69" if score >= 45 else "🧊 <45"


def trust_bucket(score: int | None) -> str:
    if score is None:
        return "?"
    return "✅ 70+" if score >= 70 else "⚠️ 50-69" if score >= 50 else "🔸 30-49" if score >= 30 else "⛔ <30"


def finding_table(results: list[dict], min_n: int = 5,
                  kinds: tuple[str, ...] = ("alert", "filtered")) -> list[tuple[str, dict]]:
    """Hit rates of the signals of `kinds` (default: analysed ones) carrying each finding code, most common first."""
    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        if r["kind"] in kinds:
            for code in set(r.get("findings") or []):
                by_code[code].append(r)
    rows = [(code, summarize(rs)) for code, rs in by_code.items() if len(rs) >= min_n]
    return sorted(rows, key=lambda row: -row[1]["n"])


# Numeric signal features worth splitting into low / mid / high thirds for /analiz, with Turkish labels.
ANALYSIS_FEATURES = {
    "rug_risk": "rug riski puanı",
    "trust": "güven skoru",
    "momentum": "momentum skoru",
    "buyers_10m": "10 dk alıcı",
    "accel_5m": "hızlanma (son 5 dk / önceki 5 dk alıcı)",
    "buy_usd_10m": "10 dk Fomo alımı ($)",
    "avg_buy_usd": "alıcı başına alım ($)",
    "buy_ratio_10m": "alım oranı (alım / toplam)",
    "hold_rate_30m": "tutma oranı (30 dk)",
    "whale_share_10m": "en büyük alıcının payı",
    "smart_buyers_10m": "akıllı cüzdan sayısı",
    "churn_share_30m": "al-sat döngüsü payı",
    "fomo_share_h1": "Fomo'nun hacim payı",
    "market_buyers_1h": "piyasa hareketliliği (1 saatte tüm Fomo alıcıları)",
    "age_min": "yaş (dk)",
    "liquidity_usd": "likidite ($)",
    "fdv": "FDV ($)",
    "top10_pct": "ilk 10 cüzdan payı (%)",
    "dev_pct": "dev payı (%)",
    "sniper_pct": "sniper payı (%)",
    "bundle_pct": "bundle payı (%)",
    "previous_launches": "dev'in önceki coin sayısı",
    "runup_first": "ilk görülmeden bu yana fiyat (x)",
    "since_first_min": "ilk görülmeden bu yana geçen dk",
    "change_m5": "son 5 dk fiyat değişimi (%)",
    "change_h1": "son 1 saat fiyat değişimi (%)",
}


def feature_value(r: dict, name: str) -> float | None:
    f = r.get("features") or {}
    if name in ("trust", "momentum"):
        value = r.get(name)
    elif name == "rug_risk":
        value = rug_risk_of(r)
    elif name == "accel_5m":
        b5, prev = f.get("buyers_5m"), f.get("buyers_prev_5m")
        value = b5 / max(prev, 1) if b5 is not None and prev is not None else None
    elif name == "avg_buy_usd":
        usd, buyers = f.get("buy_usd_10m"), f.get("buyers_10m")
        value = usd / buyers if usd is not None and buyers else None
    else:
        value = f.get(name)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def feature_table(results: list[dict], min_n: int = 30) -> list[tuple[str, list[tuple[str, dict]]]]:
    """For each feature: the signals split into thirds by its value, and how each third did."""
    table = []
    for name, label in ANALYSIS_FEATURES.items():
        valued = sorted(((v, r) for r in results if (v := feature_value(r, name)) is not None), key=lambda x: x[0])
        if len(valued) < min_n:
            continue
        cut1, cut2 = valued[len(valued) // 3][0], valued[2 * len(valued) // 3][0]
        if cut1 == cut2:  # too few distinct values for thirds (e.g. mostly 0): split at that value
            groups = [[x for x in valued if x[0] <= cut1], [x for x in valued if x[0] > cut1]]
        else:
            groups = [[x for x in valued if x[0] < cut1], [x for x in valued if cut1 <= x[0] < cut2],
                      [x for x in valued if x[0] >= cut2]]
        groups = [g for g in groups if g]
        if len(groups) < 2:
            continue
        parts = [(_range(g[0][0], g[-1][0]), [r for _, r in g]) for g in groups]
        table.append((label, [(tag, summarize(rs)) for tag, rs in parts]))
    return table


def _range(lo: float, hi: float) -> str:
    return _short(lo) if lo == hi else f"{_short(lo)}–{_short(hi)}"


def _short(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k"
    if abs(value) >= 10 or value == int(value):
        return f"{value:.0f}"
    return f"{value:.2f}"


def momentum_v2_of(r: dict) -> int | None:
    """The v2 momentum of a recorded signal: its v1 score with the re-weighted rules swapped in."""
    f = r.get("features") or {}
    if f.get("momentum_v2") is not None:
        return f["momentum_v2"]
    if r.get("momentum") is None:
        return None
    delta = sum(d for d, _ in tuned_points(f, True)) - sum(d for d, _ in tuned_points(f, False))
    return int(max(0, min(100, r["momentum"] + delta)))


def momentum_v1_of(r: dict) -> int | None:
    """The v1 momentum of a recorded signal: kept in its features since both are scored live (while v2 is on,
    the signal's own momentum is the v2 score); older signals only have the v1 score itself."""
    f = r.get("features") or {}
    return f["momentum_v1"] if f.get("momentum_v1") is not None else r.get("momentum")


def backtest(results: list[dict], min_score: int, min_momentum: int) -> list[tuple[str, dict]]:
    """Signals v1 and v2 momentum would each have alerted on, in the older and the newer half of the period.

    The v2 weights were fitted on /analiz over the whole period; the newer half is the fairer test."""
    rows = sorted((r for r in results if r.get("momentum") is not None and r.get("trust") is not None),
                  key=lambda r: r["ts"])
    halves = [("Eski yarı", rows[: len(rows) // 2]), ("Yeni yarı", rows[len(rows) // 2:]), ("Tümü", rows)]
    out = []
    for name, part in halves:
        passes_v1 = [r for r in part if r["trust"] >= min_score and (momentum_v1_of(r) or 0) >= min_momentum]
        passes_v2 = [r for r in part if r["trust"] >= min_score and (momentum_v2_of(r) or 0) >= min_momentum]
        ids1, ids2 = {id(r) for r in passes_v1}, {id(r) for r in passes_v2}
        out.append((name, {
            "v1": summarize(passes_v1),
            "v2": summarize(passes_v2),
            "added": summarize([r for r in passes_v2 if id(r) not in ids1]),
            "dropped": summarize([r for r in passes_v1 if id(r) not in ids2]),
            "all": summarize(part),
        }))
    return out


def lower_bar_candidates(shadows: list[dict], min_buyers: int, min_momentum: int, fdv_below: float = 20_000,
                         buyers_from: int = 8) -> dict:
    """Shadow signals a lower buyer bar for tiny coins would have alerted on: `buyers_from` up to the bar,
    FDV under `fdv_below` and v2 momentum over the bar (FDV is recorded for shadows only since that was added)."""
    picked = [r for r in shadows
              if buyers_from <= ((r.get("features") or {}).get("buyers_10m") or 0) < min_buyers
              and 0 < ((r.get("features") or {}).get("fdv") or 0) < fdv_below
              and (momentum_v2_of(r) or 0) >= min_momentum]
    return summarize(picked)


def blocking_gates(signal: dict, min_score: int, min_momentum: int, min_buyers: int,
                   min_buy_usd: float, max_rug: int = 101) -> list[str]:
    """Which of today's alert bars a recorded signal would fail, with its values (empty: it would alert).

    Momentum is compared as v2, the score alerts use now."""
    f = signal.get("features") or {}
    out = []
    buyers, usd = f.get("buyers_10m"), f.get("buy_usd_10m")
    if buyers is not None and buyers < min_buyers:
        out.append(f"alıcı {buyers} (eşik {min_buyers})")
    if usd is not None and usd < min_buy_usd:
        out.append(f"10 dk alım ${usd:,.0f} (eşik ${min_buy_usd:,.0f})")
    if signal.get("trust") is not None and signal["trust"] < min_score:
        out.append(f"güven {signal['trust']} (eşik {min_score})")
    momentum = momentum_v2_of(signal)
    if momentum is not None and momentum < min_momentum:
        out.append(f"momentum {momentum} (eşik {min_momentum})")
    if max_rug <= 100 and rug_risk_of(signal) >= max_rug:
        out.append(f"rug riski {rug_risk_of(signal)} (sınır {max_rug})")
    return out


SWEEP_MOMENTUM = (55, 60, 65, 70, 75, 80, 85)
SWEEP_SCORE = (0, 20, 30, 40, 50)


def parameter_sweep(results: list[dict], winner_multiple: float = 5.0, min_n: int = 15) -> list[dict]:
    """Every (min momentum v2, min trust) pair on the analysed signals: how many would alert, how they did, and
    what share of the signals that went on to `winner_multiple`x within a day each pair would have caught."""
    rows = [r for r in results if r.get("trust") is not None and momentum_v2_of(r) is not None]
    won = lambda r: (r.get("held_all") or 0) >= winner_multiple  # noqa: E731  (held, not a one-sample spike)
    winners = [r for r in rows if won(r)]
    out = []
    for min_momentum in SWEEP_MOMENTUM:
        for min_score in SWEEP_SCORE:
            picked = [r for r in rows if r["trust"] >= min_score and momentum_v2_of(r) >= min_momentum]
            if len(picked) < min_n:
                continue
            caught = sum(1 for r in picked if won(r))
            out.append({"min_momentum": min_momentum, "min_score": min_score, **summarize(picked),
                        "recall": round(100.0 * caught / len(winners), 1) if winners else None})
    return out


def rug_risk_of(r: dict) -> int:
    """The rug risk of a recorded signal, from its stored features (recorded live, or worked out again)."""
    f = r.get("features") or {}
    return f["rug_risk"] if f.get("rug_risk") is not None else rug_risk(f)[0]


def rug_filter_sweep(results: list[dict], min_momentum: int, min_score: int,
                     winner_multiple: float = 5.0) -> list[tuple[str, dict]]:
    """Today's bars plus a rug-risk ceiling: does dropping risky signals cut rugs without losing winners?"""
    base = [r for r in results if r.get("trust") is not None and r["trust"] >= min_score
            and (momentum_v2_of(r) or 0) >= min_momentum]
    winners = sum(1 for r in base if (r.get("held_all") or 0) >= winner_multiple)
    out = []
    for name, ceiling in (("filtre yok", 101), ("rug riski <60", 60), ("rug riski <40", 40), ("rug riski <20", 20)):
        kept = [r for r in base if rug_risk_of(r) < ceiling]
        caught = sum(1 for r in kept if (r.get("held_all") or 0) >= winner_multiple)
        out.append((name, {**summarize(kept), "kept_winners": caught, "winners": winners}))
    return out


EARLY_RULES = {
    "A": "büyük alıcılar: son 5 dk ≥5 alıcı, önceki 5 dk ≤1, alıcı başına ≥$100, tutma ≥0.9",
    "B": "kalabalık: son 5 dk ≥8 alıcı, önceki 5 dk ≤1, tutma ≥0.9",
}


def early_entry(f: dict, rule: str = "A") -> bool:
    """Buying that starts from nothing and is held. A: few large buys (HOODS in its shadow signal, 18 minutes
    before its alert, then 116x) - the research's strongest predictor. B: a swarm of small buys (BROBIN in the
    shadows: 8 buyers at $24 each, then 8.9x)."""
    b5, prev = f.get("buyers_5m") or 0, f.get("buyers_prev_5m") or 0
    buyers, usd, hold = f.get("buyers_10m") or 0, f.get("buy_usd_10m") or 0, f.get("hold_rate_30m")
    if prev > 1 or hold is None or hold < 0.9:
        return False
    if rule == "A":
        return b5 >= 5 and buyers > 0 and usd / buyers >= 100
    return b5 >= 8


def early_entry_candidates(results: list[dict], min_buyers: int, rule: str = "A", min_momentum: int = 0) -> dict:
    """Signals under the buyer bar (shadows) that an early-entry rule would have alerted on, at a momentum
    (v2, as scored for the shadow) of at least `min_momentum`."""
    return summarize([r for r in results if r["kind"] == "shadow" and early_entry(r.get("features") or {}, rule)
                      and ((r.get("features") or {}).get("buyers_10m") or 0) < min_buyers
                      and (momentum_v2_of(r) or 0) >= min_momentum])


EARLY_MOMENTUM_STEPS = (0, 70, 80, 85, 90)


RUNUP_LIMITS = (1.5, 2.0, 3.0, 5.0)


def lateness_table(alerts: list[dict]) -> dict:
    """/gec: alerts split by how late they came (price rise and minutes since the coin's first sighting, and the
    market's own 5 min / 1 h price change at the alert), and what a cap on the rise would keep."""
    def value(r, name):
        return (r.get("features") or {}).get(name)

    def split(rows, name, edges, labels):
        valued = [(value(r, name), r) for r in rows if value(r, name) is not None]
        out = []
        for i, label in enumerate(labels):
            lo = edges[i - 1] if i else None
            hi = edges[i] if i < len(edges) else None
            part = [r for v, r in valued if (lo is None or v >= lo) and (hi is None or v < hi)]
            out.append((label, summarize(part)))
        return out

    measured = [r for r in alerts if value(r, "runup_first") is not None]
    later = [r for r in alerts if value(r, "first_seen") == "shadow"]
    by_first = {k: [r for r in alerts if value(r, "first_seen") == k] for k in ("self", "old", "unpriced", "shadow")}
    strong = [r for r in later if (r.get("momentum") or 0) >= 85]
    held = [r for r in alerts if (r.get("held_all") or 0) >= 5]
    sweep = []
    for limit in (*RUNUP_LIMITS, None):
        kept = [r for r in alerts if limit is None or value(r, "runup_first") is None or value(r, "runup_first") < limit]
        s = summarize(kept)
        s["kept_held"] = sum(1 for r in kept if (r.get("held_all") or 0) >= 5)
        sweep.append((limit, s))
    return {
        "n": len(alerts), "measured": len(measured), "held": len(held),
        "first": [("önceden hiç görülmemiş (ilk görülme = bildirim)", summarize(by_first["self"])),
                  ("gölgesi 24 saatten eski (önceki dalga)", summarize(by_first["old"])),
                  ("gölgesi var ama fiyatı yok", summarize(by_first["unpriced"])),
                  ("24 saat içinde gölgede görülmüş (ölçülen)", summarize(by_first["shadow"]))],
        "runup": split(later, "runup_first", [1.0, 1.5, 3.0], ["düşmüş (<1x)", "1–1.5x", "1.5–3x", "3x+"]),
        "runup_strong": split(strong, "runup_first", [1.0, 1.5, 3.0], ["düşmüş (<1x)", "1–1.5x", "1.5–3x", "3x+"]),
        "since": split(later, "since_first_min", [15, 60], ["<15 dk", "15–60 dk", "60+ dk"]),
        "change_h1": split(alerts, "change_h1", [100, 500], ["<%100", "%100–500", "%500+"]),
        "change_m5": split(alerts, "change_m5", [0, 50], ["düşüşte (<%0)", "%0–50", "%50+"]),
        "sweep": sweep,
        "confirm": confirm_table(alerts),
    }


MAX_RUNUP = 3.0  # /gecfiltre: no alert once the price is this many times its first-sighting price


def late_block(first: tuple[float, float | None] | None, now: float, price: float | None,
               max_runup: float = MAX_RUNUP) -> tuple[str | None, float | None, float | None]:
    """/gecfiltre at alert time: (reason to hold the alert back or None, price ÷ first-sighting price, minutes
    since the first sighting). /gec: coins first seen over a day ago (an earlier wave) and coins already up 3x+
    since first seen rarely held 5x and often rugged."""
    if not first:
        return None, None, None
    first_ts, first_price = first
    age_min = round(max(0.0, now - first_ts) / 60, 1)
    if now - first_ts > LATE_WINDOW:
        return f"önceki dalga (ilk görülme {age_min / 60:.0f} saat önce)", None, age_min
    runup = round(price / first_price, 2) if price and first_price else None
    if runup is not None and runup >= max_runup:
        return f"ilk görülmeden bu yana {runup:g}x yükselmiş", runup, age_min
    return None, runup, age_min


CONFIRM_STEPS = (1.2, 1.3, 1.5)
CONFIRM_WAIT_MIN = 60


def confirm_entry(r: dict, step: float, wait_min: int = CONFIRM_WAIT_MIN) -> dict | None:
    """Waiting for the price to move before buying: the first sample within `wait_min` minutes at `step` times
    the alert price is the entry. None: it never moved that much (no trade). Outcomes are relative to the entry."""
    path = r.get("path") or []
    hit = next((i for i, (m, x) in enumerate(path) if 0 < m <= wait_min and x >= step), None)
    if hit is None:
        return None
    entry_min, entry = path[hit]
    after = [x / entry for _, x in path[hit:]]
    at60 = next((x / entry for m, x in path[hit:] if m >= entry_min + 60), None)
    return {"entry_min": entry_min, "entry": entry, "held": max((min(a, b) for a, b in zip(after, after[1:])), default=0),
            "max": max(after), "ret_60": at60}


def confirm_table(alerts: list[dict]) -> list[tuple[str, list[tuple[str, dict]]]]:
    """/gec: buying at the alert vs waiting for the price to rise 20/30/50% first (within an hour), for the flat
    alerts (1–1.5x since first sighting) and for all of them."""
    def stats(rows, step):
        held5 = [r for r in rows if (r.get("held_all") or 0) >= 5]
        if step is None:
            ret = [r["ret_60"] for r in rows if r.get("ret_60") is not None]
            return {"n": len(rows), "entered": len(rows),
                    "x5_held": round(100.0 * len(held5) / len(rows), 1) if rows else 0,
                    "x2": round(100.0 * sum(1 for r in rows if (r.get("max_all") or 0) >= 2) / len(rows), 1) if rows else 0,
                    "median_ret60": round(statistics.median(ret), 2) if ret else None,
                    "kept": len(held5), "winners": len(held5)}
        entries = [(r, e) for r in rows if (e := confirm_entry(r, step))]
        ret = [e["ret_60"] for _, e in entries if e["ret_60"] is not None]
        n = len(entries)
        return {"n": len(rows), "entered": n,
                "x5_held": round(100.0 * sum(1 for _, e in entries if e["held"] >= 5) / n, 1) if n else 0,
                "x2": round(100.0 * sum(1 for _, e in entries if e["max"] >= 2) / n, 1) if n else 0,
                "median_ret60": round(statistics.median(ret), 2) if ret else None,
                "kept": sum(1 for r, e in entries if e["held"] >= 5), "winners": len(held5)}

    flat = [r for r in alerts if (r.get("features") or {}).get("first_seen") == "shadow"
            and 1.0 <= (r["features"].get("runup_first") or 0) < 1.5]
    out = []
    for title, rows in (("Fiyatı yerinde sayanlar (ilk görülmeden 1–1.5x)", flat), ("Tüm bildirimler", alerts)):
        out.append((title, [("hemen gir", stats(rows, None)),
                            *((f"%{round((k - 1) * 100)} yükselince gir", stats(rows, k)) for k in CONFIRM_STEPS)]))
    return out


EARLY_GRID = {"b5": (3, 4, 5, 6, 8), "prev": (0, 1, 2), "avg": (0, 50, 100, 150, 200), "hold": (0.8, 0.9, 1.0),
              "mom": (80, 85, 90, 95)}
EARLY_LIVE = {"b5": 5, "prev": 1, "avg": 100, "hold": 0.9, "mom": 90}


def early_grid(shadows: list[dict], min_buyers: int, position: float, fee_pct: float, fee_min: float,
               min_half: int = 8) -> dict:
    """/erkenayar: every combination of the early rule's settings, replayed on the shadows under the buyer bar
    with the chosen exit (3x, else out at 60 min; $ per trade with Fomo's fee). The signals are split in time:
    settings are ranked on the older half only, the newer half is the honest test."""
    from .strategy import delayed, target_exit, trade_pnl
    rule = target_exit(3.0, 60)
    rows = []
    for r in shadows:
        f = r.get("features") or {}
        if (f.get("buyers_10m") or 0) >= min_buyers or not r.get("path") or f.get("hold_rate_30m") is None:
            continue
        late = delayed(r["path"])
        rows.append({"ts": r["ts"], "b5": f.get("buyers_5m") or 0, "prev": f.get("buyers_prev_5m") or 0,
                     "avg": (f.get("buy_usd_10m") or 0) / f["buyers_10m"] if f.get("buyers_10m") else 0,
                     "hold": f["hold_rate_30m"], "mom": momentum_v2_of(r) or 0,
                     "pnl": trade_pnl(rule(r["path"], None), position, fee_pct, fee_min),
                     "late": trade_pnl(rule(late, None), position, fee_pct, fee_min) if late else None})
    if not rows:
        return {"n": 0, "combos": [], "live": None}
    cut = sorted(x["ts"] for x in rows)[len(rows) // 2]

    def stats(p: dict) -> dict:
        picked = [x for x in rows if x["b5"] >= p["b5"] and x["prev"] <= p["prev"] and x["avg"] >= p["avg"]
                  and x["hold"] >= p["hold"] and x["mom"] >= p["mom"]]
        old = [x["pnl"] for x in picked if x["ts"] < cut]
        new = [x["pnl"] for x in picked if x["ts"] >= cut]
        late = [x["late"] for x in picked if x["late"] is not None]
        per = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
        return {**p, "n": len(picked), "n_old": len(old), "n_new": len(new), "old": per(old), "new": per(new),
                "late": per(late), "win": round(100.0 * sum(1 for x in picked if x["pnl"] > 0) / len(picked), 1)
                if picked else None}

    combos = []
    for b5 in EARLY_GRID["b5"]:
        for prev in EARLY_GRID["prev"]:
            for avg in EARLY_GRID["avg"]:
                for hold in EARLY_GRID["hold"]:
                    for mom in EARLY_GRID["mom"]:
                        s = stats({"b5": b5, "prev": prev, "avg": avg, "hold": hold, "mom": mom})
                        if s["n_old"] >= min_half and s["n_new"] >= min_half:
                            combos.append(s)
    return {"n": len(rows), "combos": combos, "live": stats(EARLY_LIVE),
            "by_old": sorted(combos, key=lambda s: -s["old"])[:8],
            "steady": sorted(combos, key=lambda s: -min(s["old"], s["new"]))[:8]}
