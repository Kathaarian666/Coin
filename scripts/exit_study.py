"""Which trade rules make the alerts most profitable? (user, 4 Oct: "farklı parametrelerle kârlılığı yukarı taşı")

  python scripts/exit_study.py <trades.db> <walk-forward picks.parquet> [<last exploration day>=2026-09-30]

Alerts: the walk-forward picks of the research (scripts/profit_study.py output, 5th buyer, each day scored by a model
trained on the days before), so no rule is tried on picks the model saw. Rules searched, on the user's trade (30 s
late at the last price then, Fomo fee + price impact, $1000 fresh every week):
- tp: the target as a multiple of the alert price (two buys in a row at or above it, PROJE.md §6), tp_share sold there
- stop: sell everything once two trades in a row are at <= (1 - stop) x the buy price, before the target
- trail: after the target, the rest is sold once two trades in a row are at <= (1 - trail) x the highest price held
  (two buys); none = keep
- hold: everything still held is sold at this many hours after the alert (median of the last 5 prices, dead coin half)
- pick: the top 1 / 2 / 5 % of the model's scores; size: 4/2/1 % of the bankroll by rank, or a flat 2 %
Only the days up to <last exploration day> are used to choose (the later days are the final exam, PROJE.md §0 D7);
ranked by the weekly geometric mean (costs in), with the worst week and the result without the best 1 % of trades.
"""

import itertools
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trade_sim  # noqa: E402
from security_extra import depth_at  # noqa: E402

DELAY = 30
DEAD = 6 * 3600
TPS = (1.5, 2.0, 3.0)
SHARES = (0.0, 1 / 3, 0.5, 1.0)
STOPS = (0.3, 0.5, 0.7, None)
TRAILS = (0.3, 0.5, None)
HOLDS = (6, 24, None)
PICKS = (0.01, 0.02, 0.05)


def first_two(mask: np.ndarray) -> int | None:
    hit = np.flatnonzero(mask[1:] & mask[:-1])
    return int(hit[0]) + 1 if len(hit) else None


class Path_:
    """One alert's price path after the user's buy."""

    def __init__(self, ts, px, side, t_alert, data_end):
        self.t_alert = t_alert
        b = (side == 1) & np.isfinite(px) & (px > 0)
        self.p_alert = px[b & (ts <= t_alert)][-1]
        self.t_in = t_alert + DELAY
        self.p_in = px[b & (ts <= self.t_in)][-1]
        after = (ts > self.t_in) & np.isfinite(px) & (px > 0)
        self.ts, self.side = ts[after], side[after]
        self.px = np.minimum(px[after], trade_sim.CAP * self.p_alert)
        self.data_end = data_end
        self.buys = self.side == 1

    def price_at(self, t):
        i = np.searchsorted(self.ts, t, side="right") - 1
        if i < 0:
            return self.p_in
        p = float(np.median(self.px[max(0, i - 4):i + 1]))
        return p / 2 if t - self.ts[i] > DEAD else p

    def legs(self, tp, share, stop, trail, hold):
        """[(time, share, price)] closing the whole position."""
        t_end = self.data_end if hold is None else min(self.data_end, self.t_alert + 3600 * hold)
        bts, bpx = self.ts[self.buys], self.px[self.buys]
        j = first_two(bpx >= tp * self.p_alert)
        t_tp = bts[j] if j is not None else np.inf
        t_stop, p_stop = np.inf, None
        if stop is not None:
            k = first_two(self.px <= (1 - stop) * self.p_in)
            if k is not None:
                t_stop, p_stop = self.ts[k], self.px[k]
        if min(t_tp, t_stop) > t_end:  # neither before the time limit
            return [(t_end, 1.0, self.price_at(t_end))]
        if t_stop < t_tp:
            return [(t_stop, 1.0, p_stop)]
        out = [(t_tp, share, tp * self.p_alert)] if share > 0 else []
        rest = 1.0 - share
        if rest <= 1e-9:
            return out
        if trail is not None:
            later = self.ts > t_tp
            peak, prev, below = tp * self.p_alert, None, 0
            for t, p, s in zip(self.ts[later], self.px[later], self.side[later]):
                if t > t_end:
                    break
                if s == 1:
                    if prev is not None:
                        peak = max(peak, min(prev, p))
                    prev = p
                below = below + 1 if p <= (1 - trail) * peak else 0
                if below == 2:
                    return out + [(t, rest, p)]
        return out + [(t_end, rest, self.price_at(t_end))]


def weeks(alerts, rule_key, sizing, bank0=1000.0):
    first = min(a["t_in"] for a in alerts)
    by_week = {}
    for a in alerts:
        by_week.setdefault(int((a["t_in"] - first) // (7 * 86400)), []).append(a)
    res = []
    for wk, al in sorted(by_week.items()):
        span = (max(a["t_in"] for a in al) - (first + wk * 7 * 86400)) / 86400
        if span < 3:
            continue
        for a in al:
            a["size"] = a[sizing]
            a["events"] = {"x": a["legs"][rule_key]}
        res.append(trade_sim.simulate(al, "x", bank0, True) / bank0)
    return res


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)
    picks = pd.read_parquet(sys.argv[2])
    last = pd.Timestamp(sys.argv[3] if len(sys.argv) > 3 else "2026-09-30").value / 1e9 + 86400
    picks = picks[picks.ts < last].sort_values("ts")
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    data_end = min(db.execute("SELECT MAX(ts) FROM trades").fetchone()[0], last + 3 * 86400)
    alerts = []
    for r in picks.itertuples():
        g = pd.read_sql("SELECT ts, side, usd, amount FROM trades WHERE token = ? AND ts <= ? ORDER BY ts", db,
                        params=(names[r.coin], data_end))
        ts, side, usd = g.ts.values, g.side.values, g.usd.values
        px = np.where(g.amount > 0, g.usd / g.amount.where(g.amount > 0), np.nan)
        b = (side == 1) & np.isfinite(px)
        path = Path_(ts, px, side, r.ts, data_end)
        alerts.append({"t_in": path.t_in, "p_in": path.p_in, "pct": r.pct, "path": path,
                       "depth": depth_at(px[b], usd[b], ts[b], r.ts)})
    med = np.nanmedian([a["depth"] for a in alerts])
    for a in alerts:
        if not np.isfinite(a["depth"]):
            a["depth"] = med
    rules = list(itertools.product(TPS, SHARES, STOPS, TRAILS, HOLDS))
    rules = [r for r in rules if not (r[1] == 1.0 and r[3] is not None)]  # nothing left to trail
    for a in alerts:
        a["legs"] = {r: a["path"].legs(*r) for r in rules}
    rows = []
    for pick in PICKS:
        sel = [a for a in alerts if a["pct"] >= 1 - pick]
        ranks = pd.Series([a["pct"] for a in sel]).rank(pct=True).values
        for a, q in zip(sel, ranks):
            a["ranked"] = 0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01
            a["flat"] = 0.02
        for rule in rules:
            for sizing in ("ranked", "flat"):
                w = weeks(sel, rule, sizing)
                mult = [sum(sh * p for _, sh, p in a["legs"][rule]) / a["p_in"] for a in sel]
                cut = np.quantile(mult, 0.99)
                luck = [a for a, m in zip(sel, mult) if m < cut]
                wl = weeks(luck, rule, sizing)
                rows.append({"pick": pick, "tp": rule[0], "share": round(rule[1], 2), "stop": rule[2], "trail": rule[3],
                             "hold": rule[4], "size": sizing, "n": len(sel),
                             "weeks": " / ".join(f"{x:.2f}" for x in w), "geo": float(np.prod(w) ** (1 / len(w))),
                             "worst": min(w), "geo_luck": float(np.prod(wl) ** (1 / len(wl)))})
    df = pd.DataFrame(rows).sort_values("geo", ascending=False)
    df.to_parquet(Path(sys.argv[2]).with_name("exit_study.parquet"), index=False)
    base = df[(df.pick == 0.02) & (df.tp == 2.0) & (df.share == 0.5) & (df.stop == 0.5) & (df.trail == 0.5)
              & df.hold.isna() & (df["size"] == "ranked")]
    cols = ["pick", "tp", "share", "stop", "trail", "hold", "size", "weeks", "geo", "worst", "geo_luck"]
    print(f"{len(rules)} kural x {len(PICKS)} seçim x 2 tutar = {len(df)} deneme; deneme günleri: "
          f"{pd.to_datetime(picks.ts.min(), unit='s'):%d %b} – {pd.to_datetime(picks.ts.max(), unit='s'):%d %b}\n")
    print("Şimdiki kurallar (en iyi %2, 2x'te yarı, %50 zarar-kes, zirveden %50, süresiz, 4/2/1):")
    print(base[cols].to_string(index=False))
    print("\nEn iyi 15 (haftalık geometrik ortalamaya göre):")
    print(df.head(15)[cols].to_string(index=False))
    print("\nEn kötü haftası en iyi 10 (en az 1,2x):")
    print(df[df.worst >= 1.2].sort_values("worst", ascending=False).head(10)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
