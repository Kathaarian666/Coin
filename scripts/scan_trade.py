"""Trading the scan: coins picked at their 3rd Fomo buyer, with entry, exit rules and costs.

  python scripts/scan_trade.py <trades.db> <winners_with_transfers.parquet> [<train share>=0.65]

The scan (gradient boosting on >= 5x, Fomo flow + holder features, scripts/rise_detect.py) is trained on the
first 65% of the period; trades are simulated on the last 35% only. Entry 30 s after the checkpoint at the pool
price then (median of the last 3 Fomo buys, marked up for the last buy's impact), $100, Fomo's fee (0.5%, at
least $0.95) and slippage from the pool depth of the last 15 minutes (unknown: a pessimistic $3k). Up moves are read on Fomo
buys held two in a row, down moves and time exits on all trades; one coin's multiple is capped at 100x.
"""

import bisect
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rise_build import depth_at, depth_prefix, money_back, needed  # noqa: E402
from rise_detect import FLOW, HOLD  # noqa: E402

DELAY, HORIZON, CAP, UNKNOWN_DEPTH, POS = 30, 72 * 3600, 100.0, 3000.0, 100.0


def path_after(ts, px, t_in, p_in):
    """Price multiples over the entry after t_in, and their times."""
    lo, hi = bisect.bisect_right(ts, t_in), bisect.bisect_right(ts, t_in + HORIZON)
    return px[lo:hi] / p_in, ts[lo:hi]


def exits(held, h_t, allp, a_t, t_in, depth):
    """$ result of each exit rule. Up moves (targets, the running high) are read on buys held two in a row; down
    moves and time exits on all trades (a coin crashes through sells). A coin with no trade in the last 6 h before
    a time exit is taken as dead: half its last price."""
    val = lambda m: money_back(min(m, CAP), depth) - POS  # noqa: E731

    def at(T, cap=np.inf):
        """Value at T, never above what buys held so far (or `cap`): a lone sell print above it is a data error."""
        k = bisect.bisect_right(a_t, T)
        if k == 0:
            return 1.0
        w = allp[bisect.bisect_left(a_t, T - 600):k]
        v = float(np.median(w)) if len(w) else float(allp[k - 1])
        seen = held[h_t <= T]
        v = min(v, cap, max(1.0, seen.max()) if len(seen) else 1.0)
        return v * (0.5 if T - a_t[k - 1] > 6 * 3600 else 1.0)

    def first_hit(m, until=np.inf):
        k = np.nonzero(held >= m)[0]
        return h_t[k[0]] if len(k) and h_t[k[0]] <= until else None

    def trail_exit(x, since):
        """Sell when a trade prints (1 - x) under the high held since `since` (at least the entry)."""
        run = np.maximum.accumulate(np.where(h_t >= since, held, 1.0)) if len(held) else held
        for t, p in zip(a_t, allp):
            if t < since:
                continue
            k = bisect.bisect_right(h_t, t) - 1
            high = max(1.0, run[k]) if k >= 0 else 1.0
            if p <= (1 - x) * high:
                return min(p, high) * 0.95
        return at(t_in + HORIZON)

    out, end = {}, t_in + HORIZON
    two = needed(round(depth, -2), 2.0)  # price multiple that returns 2x the money after costs
    for target in (2, 3, 5, 10):
        m = needed(round(depth, -2), float(target))
        out[f"{target}x'te sat (yoksa 72 s)"] = val(m) if first_hit(m) else val(at(end, m))
    for hours in (1, 6, 24):
        out[f"2x'te sat, yoksa {hours} s sonra çık"] = (
            val(two) if first_hit(two, t_in + hours * 3600) else val(at(t_in + hours * 3600, two)))
    for x in (0.3, 0.5):
        out[f"iz süren stop %{x * 100:.0f}"] = val(trail_exit(x, t_in))
        t2 = first_hit(two)
        out[f"yarısı 2x + kalanı iz süren %{x * 100:.0f}"] = (
            (money_back(two, depth) + money_back(min(trail_exit(x, t2), CAP), depth)) / 2 - POS
            if t2 else out[f"iz süren stop %{x * 100:.0f}"])
    out["72 saat tut"] = val(at(end))
    return out


def main():
    db = sqlite3.connect(sys.argv[1])
    df = pd.read_parquet(sys.argv[2])
    df = df[df.k == 3].sort_values("ts").reset_index(drop=True)
    feats = FLOW + [c for c in HOLD if c in df]
    df[feats] = df[feats].astype(float)
    split = df.ts.quantile(float(sys.argv[3]) if len(sys.argv) > 3 else 0.65)
    tr, te = df[df.ts < split], df[df.ts >= split].copy()
    gbm = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.04, min_samples_leaf=40, l2_regularization=1.0,
                                         random_state=0).fit(tr[feats], tr.peak >= 5)
    te["score"] = gbm.predict_proba(te[feats])[:, 1]
    ids = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    rows = []
    for coin, t, score in zip(te.coin, te.ts, te.score):
        tr = db.execute("SELECT ts, side, usd, amount FROM trades WHERE token = ? AND usd > 0 AND amount > 0 "
                        "ORDER BY ts", (ids[coin],)).fetchall()
        ats = np.array([x[0] for x in tr], float)
        apx = np.array([x[2] / x[3] for x in tr], float)
        buy = np.array([x[1] == 1 for x in tr])
        bts, bpx, busd = ats[buy], apx[buy], np.array([x[2] for x in tr], float)[buy]
        t_in = t + DELAY
        e = bisect.bisect_right(bts, t_in) - 1
        depth, known = depth_at(depth_prefix(bts, bpx, busd), t)
        depth = depth if known else UNKNOWN_DEPTH
        p_in = float(np.median(bpx[max(0, e - 2):e + 1])) * (1 + 1.5 * busd[e] / depth)
        bp, bt = path_after(bts, bpx, t_in, p_in)
        held = np.minimum(np.minimum(bp[:-1], bp[1:]), CAP) if len(bp) > 1 else np.array([])
        allp, a_t = path_after(ats, apx, t_in, p_in)
        rows.append({"coin": coin, "ts": t, "score": score, "depth": depth,
                     "peak": held.max() if len(held) else 0.0,
                     **exits(held, bt[1:], np.minimum(allp, CAP), a_t, t_in, depth)})
    res = pd.DataFrame(rows)
    rules = [c for c in res.columns if c not in ("coin", "ts", "score", "depth", "peak")]
    days = (res.ts.max() - res.ts.min()) / 86400
    print(f"Test dönemi {days:.1f} gün, {len(res)} coin (3. Fomo alıcısı). İşlem başı $ ($100, maliyetler dahil):\n")
    groups = [("Hepsi (seçimsiz)", res)] + [
        (f"Taramanın en iyi %{q}'u", res[res.score >= np.percentile(res.score, 100 - q)]) for q in (5, 10, 20)]
    for name, g in groups:
        day = (g.ts // 86400).astype(int)
        print(f"== {name}: {len(g)} coin ({len(g) / days:.0f}/gün) · girişten sonra zirve ≥2x %{100 * (g.peak >= 2).mean():.0f}"
              f" · ≥5x %{100 * (g.peak >= 5).mean():.0f} · ≥10x %{100 * (g.peak >= 10).mean():.0f}")
        for r in rules:
            v = g[r].values
            best_out = np.sort(v)[:-max(1, len(v) // 100)].mean()
            pos_days = (g[r].groupby(day).mean() > 0).sum()
            se = v.std() / np.sqrt(len(v))
            print(f"   {r:38} ort {v.mean():+6.1f}$ (±{1.64 * se:4.1f}) · en iyi %1 hariç {best_out:+6.1f}$ · medyan {np.median(v):+6.1f}$"
                  f" · kârlı %{100 * (v > 0).mean():.0f} · artı gün {pos_days}/{day.nunique()}")


if __name__ == "__main__":
    main()
