"""Which exit strategy, honestly? A grid of take-profit ladders, trailing stops, stop-losses and holding times on
the coins the walk-forward scan picks.

  python scripts/exit_search.py <trades.db> <winners_with_transfers.parquet> [<fresh winners.parquet> ...]

Picks: the scan of scan_trade.py (Fomo flow features only, 3rd Fomo buyer), retrained every day on the earlier
days (label 5x within 24 h), top 10% / 20% by the bars of the 2 days before. Entry 30 s later at the pool price,
$100, Fomo's fee and slippage. Prices: up moves on buys held two in a row, down moves and time exits on all
trades, dead coins (6 h without a trade) at half price, 100x cap; positions still open when the data ends are
valued at the last prices. Exit choice is walk-forward too: each day uses the strategy that did best on the
days before it (the best-in-hindsight row is shown only as an upper bound).
"""

import bisect
import itertools
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rise_build import depth_at, depth_prefix, money_back  # noqa: E402
from rise_detect import FLOW  # noqa: E402

DELAY, CAP, UNKNOWN_DEPTH, POS, FILL = 30, 100.0, 3000.0, 100.0, 0.95
HORIZON = 7 * 86400
LADDERS = {"satış yok": (), "2x'te 1/2": ((2, .5),), "3x'te 1/2": ((3, .5),), "2x+5x'te 1/3": ((2, 1 / 3), (5, 1 / 3)),
           "2x+4x+8x'te 1/4": ((2, .25), (4, .25), (8, .25)), "5x'te 1/2": ((5, .5),)}
TRAILS = (None, 0.2, 0.3, 0.4, 0.5, 0.6)
ARM = ("baştan", "ilk satıştan sonra")
STOPS = (None, 0.5, 0.7)
LIMITS = {"1 s": 3600, "6 s": 6 * 3600, "24 s": 86400, "3 g": 3 * 86400, "7 g": 7 * 86400}


class Path_:
    """One trade's price path, as multiples of the entry price."""

    def __init__(self, held, h_t, allp, a_t, t_in, depth, data_end):
        self.held, self.h_t, self.allp, self.a_t = held, h_t, allp, a_t
        self.t_in, self.depth, self.end_data = t_in, depth, data_end
        run = np.maximum.accumulate(held) if len(held) else held
        k = np.searchsorted(h_t, a_t, side="right") - 1  # running high from buys, seen at each trade
        self.high = np.where(k >= 0, np.maximum(run[np.clip(k, 0, None)] if len(run) else 1.0, 1.0), 1.0)

    def first_up(self, m):
        k = np.nonzero(self.held >= m)[0]
        return self.h_t[k[0]] if len(k) else np.inf

    def value_at(self, T):
        T = min(T, self.end_data)
        k = bisect.bisect_right(self.a_t, T)
        if k == 0:
            return 1.0
        w = self.allp[bisect.bisect_left(self.a_t, T - 600):k]
        v = float(np.median(w)) if len(w) else float(self.allp[k - 1])
        seen = self.held[self.h_t <= T]
        v = min(v, max(1.0, seen.max()) if len(seen) else 1.0)
        return v * (0.5 if T - self.a_t[k - 1] > 6 * 3600 else 1.0)

    def run(self, ladder, trail, arm, stop, limit):
        cash, left, t_first = 0.0, 1.0, np.inf
        sells = sorted((self.first_up(m), m, f) for m, f in ladder)
        t_end = self.t_in + limit
        # the exit of what is left: stop-loss, trailing stop (armed now or after the first sale), time limit
        t_stop = np.inf
        if stop:
            k = np.nonzero(self.allp <= stop)[0]
            t_stop = self.a_t[k[0]] if len(k) else np.inf
        for t, m, f in sells:
            if t < min(t_end, t_stop):
                t_first = min(t_first, t)
        t_trail, p_trail = np.inf, None
        if trail:
            since = self.t_in if arm == "baştan" else t_first
            if since < np.inf:
                i0 = bisect.bisect_left(self.a_t, since)
                hit = np.nonzero(self.allp[i0:] <= (1 - trail) * self.high[i0:])[0]
                if len(hit):
                    t_trail, p_trail = self.a_t[i0 + hit[0]], min(self.allp[i0 + hit[0]], self.high[i0 + hit[0]])
        t_out = min(t_end, t_stop, t_trail)
        for t, m, f in sells:
            if t < t_out:
                cash += f * money_back(m, self.depth)
                left -= f
        if t_out == t_stop:
            m_out = stop * 0.9
        elif t_out == t_trail:
            m_out = p_trail * FILL
        else:
            m_out = self.value_at(t_end)
        return cash + left * money_back(min(m_out, CAP), self.depth) - POS


def paths_and_peak24(db, df):
    """Each checkpoint's price path after a 30 s entry, and the highest multiple held within 24 h (the label)."""
    ids = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    paths, peak24 = {}, {}
    for coin, t in zip(df.coin, df.ts):
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
        lo, hi = bisect.bisect_right(bts, t_in), bisect.bisect_right(bts, t_in + HORIZON)
        bp = bpx[lo:hi] / p_in
        held = np.minimum(np.minimum(bp[:-1], bp[1:]), CAP) if len(bp) > 1 else np.array([])
        h_t = bts[lo + 1:hi]
        la, ha = bisect.bisect_right(ats, t_in), bisect.bisect_right(ats, t_in + HORIZON)
        paths[(coin, t)] = Path_(held, h_t, np.minimum(apx[la:ha] / p_in, CAP), ats[la:ha], t_in, depth, data_end)
        d1 = held[h_t <= t_in + 86400]
        peak24[(coin, t)] = d1.max() if len(d1) else 0.0
    return paths, peak24


def picks(db, df):
    """The walk-forward scan's top-20% picks with their day bars, and each pick's price path."""
    paths, peak24 = paths_and_peak24(db, df)
    df = df.assign(peak24=[peak24[(c, t)] for c, t in zip(df.coin, df.ts)], day=(df.ts // 86400).astype(int))
    out = []
    for d in sorted(df.day.unique()):
        start = d * 86400
        train = df[df.ts < start - 86400]
        if not len(train) or train.ts.max() - train.ts.min() < 3 * 86400:
            continue
        gbm = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.04, min_samples_leaf=40, l2_regularization=1.0,
                                             random_state=0).fit(train[FLOW], train.peak24 >= 5)
        recent = df[(df.ts >= start - 2 * 86400) & (df.ts < start)]
        today = df[df.day == d].copy()
        if today.empty or recent.empty:
            continue
        today["score"] = gbm.predict_proba(today[FLOW])[:, 1]
        s_recent = gbm.predict_proba(recent[FLOW])[:, 1]
        today["bar10"], today["bar20"] = np.percentile(s_recent, 90), np.percentile(s_recent, 80)
        out.append(today[today.score >= today.bar20])
    return pd.concat(out), paths


def main():
    db = sqlite3.connect(sys.argv[1])
    t0 = time.time()
    frames = [pd.read_parquet(p) for p in sys.argv[2:]]
    df = pd.concat([f[f.k == 3][["coin", "ts"] + FLOW] for f in frames]).sort_values("ts").reset_index(drop=True)
    df[FLOW] = df[FLOW].astype(float)
    sel, paths = picks(db, df)
    print(f"{len(sel)} seçim (en iyi %20), {sel.day.nunique()} test günü, yollar hazır ({time.time() - t0:.0f} sn)", flush=True)
    grid = [(ln, tr, arm, st, lm) for ln, tr, arm, st, lm in itertools.product(LADDERS, TRAILS, ARM, STOPS, LIMITS)
            if not (tr is None and arm != "baştan") and not (arm != "baştan" and not LADDERS[ln])]
    res = np.array([[paths[(c, t)].run(LADDERS[ln], tr, arm, st, LIMITS[lm]) for ln, tr, arm, st, lm in grid]
                    for c, t in zip(sel.coin, sel.ts)])
    print(f"{len(grid)} strateji × {len(sel)} işlem ({time.time() - t0:.0f} sn)\n", flush=True)
    name = lambda g: (f"{g[0]} · iz süren {'yok' if g[1] is None else f'%{g[1] * 100:.0f} ({g[2]})'} · "  # noqa: E731
                      f"zarar-kes {'yok' if g[3] is None else f'{g[3]}x'} · en çok {g[4]}")
    for label, mask in (("en iyi %10", (sel.score >= sel.bar10).values), ("en iyi %20", np.ones(len(sel), bool))):
        r, days = res[mask], sel.day.values[mask]
        udays = sorted(set(days))
        means = r.mean(axis=0)
        order = np.argsort(-means)
        print(f"===== Taramanın {label}: {mask.sum()} işlem, {len(udays)} gün =====")
        print("  Geriye bakınca en iyi 10 strateji (iyimser; seçim aynı veride):")
        for i in order[:10]:
            v = r[:, i]
            pos = sum(v[days == d].mean() > 0 for d in udays)
            print(f"    {means[i]:+7.1f}$ (±{1.64 * v.std() / np.sqrt(len(v)):4.1f}) · medyan {np.median(v):+6.1f}$ · "
                  f"artı gün {pos}/{len(udays)} · {name(grid[i])}")
        fixed = grid.index(("2x'te 1/2", 0.3, "baştan", None, "3 g"))
        # walk-forward exit choice: each day the strategy with the best mean over the days before (>= 2 days)
        wf = []
        for d in udays:
            past = np.isin(days, [x for x in udays if x < d])
            if len(set(days[past])) < 2:
                continue
            best = int(np.argmax(r[past].mean(axis=0)))
            wf.append((d, best, r[days == d, best]))
        v = np.concatenate([x[2] for x in wf])
        fv = np.concatenate([r[days == d, fixed] for d, _, _ in wf])
        print(f"  Her gün geçmişte en iyi stratejiyi seç (dürüst): {len(v)} işlem · ort {v.mean():+.1f}$ "
              f"(±{1.64 * v.std() / np.sqrt(len(v)):.1f}) · aynı günlerde 'yarısı 2x + %30 iz süren' {fv.mean():+.1f}$")
        from collections import Counter
        for (i, n) in Counter(b for _, b, _ in wf).most_common(4):
            print(f"    seçilen ({n} gün): {name(grid[i])}")
        # how the families compare (mean over all their variants): which knobs matter
        frame = pd.DataFrame(grid, columns=["satış", "iz", "kurulum", "zarar-kes", "süre"]).assign(ort=means)
        for col in ("satış", "iz", "zarar-kes", "süre"):
            print(f"  {col}: " + " · ".join(f"{k}: {v:+.1f}$" for k, v in frame.groupby(col, dropna=False).ort.max().items()))
        print()


if __name__ == "__main__":
    main()
