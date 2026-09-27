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

log = logging.getLogger(__name__)

CHECKPOINTS_MIN = [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360, 720, 1440]
BATCH = 30

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
                # Shadow signals are scored here, from the same data an alert would have seen.
                updates["momentum"] = momentum_fn(json.loads(features or "{}"), pairs, updates.get("pair"))
            sets = ", ".join(f"{k} = ?" for k in updates)
            self.db.execute(f"UPDATE signals SET {sets} WHERE id = ?", (*updates.values(), signal_id))
            written += 1
        self.db.commit()
        return written

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
            at60 = next((p / p0 for m, p, _ in priced if m == 60), None)
            last_m, last_p, last_l = priced[-1]
            rugged = last_p / p0 <= 0.1 or (l0 and last_l is not None and last_l / l0 <= 0.2)
            out.append({
                "token": token, "kind": kind, "trust": trust, "momentum": momentum,
                "max_60": max(within(60), default=None),
                "max_all": max(within(1440), default=None),
                "ret_60": at60,
                "last_min": last_m,
                "rugged": bool(rugged),
                "findings": json.loads(features or "{}").get("findings") or [],
            })
        return out


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
