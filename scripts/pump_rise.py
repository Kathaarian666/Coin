"""pump.fun rise criteria, first walk-forward check (PROJE.md §0 A8, step 2; the twin of scripts/profit_study.py).

  python scripts/pump_rise.py <pump_study.parquet> [k=5] [h=6] [--max-curve C]

Moments from scripts/pump_study.py at the k-th Fomo buyer. Label: two buys in a row at >= 2x within h hours. Only
moments with at least h hours of data after them are used (hit or not, so the data end cannot lift the rate).
Each test day is scored by a model trained on the days before it (HistGradientBoosting, the bot's settings); picks =
the day's top 2 % / 5 % of scores (the day's own quantile: a slight look at the same day's score spread, not at
outcomes). Reported per pick group: 2x rate, trap (<= 10 % of the alert price within 1 h with no 2x first), graduated;
and the single criteria that matter most (permutation importance on the test days).
--max-curve C: coins whose curve is more than C % sold at the moment are left out of training and picks (graduation
dump: nearly all traps are above ~90 %, PROJE.md §4.5d; seen on the first two days alone too); unknown fill stays.
"""

import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance

FEATURES = ["mins_to_k", "trades_to_k", "usd_all", "usd_per_trade", "max_buy", "sellers", "early_sold",
            "sell_usd_share", "buyers_5m", "usd_10m", "buyers_60s", "usd_60s_share", "runup", "mcap", "age_min",
            "old_coin", "curve_pct", "same_slot_buys", "small_buy_share", "creator_prev"]
PARAMS = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, random_state=0)


def line(g: pd.DataFrame) -> str:
    return (f"{len(g):5d} an · 2x %{100 * g.y.mean():4.1f} · tuzak %{100 * g.trap_1h.mean():4.1f} · "
            f"mezun %{100 * g.graduated.mean():4.1f}")


def main():
    args, max_curve = sys.argv[1:], None
    if "--max-curve" in args:
        i = args.index("--max-curve")
        max_curve = float(args[i + 1])
        del args[i:i + 2]
    k = int(args[1]) if len(args) > 1 else 5
    h = float(args[2]) if len(args) > 2 else 6.0
    d = pd.read_parquet(args[0])
    d = d[(d.k == k) & (d.obs_h >= h)].copy()
    if max_curve is not None:
        d = d[~(d.curve_pct > max_curve)]  # NaN (unknown) stays
    d["y"] = (d.t2x_h <= h).astype(int)
    d["old_coin"] = d.old_coin.astype(int)
    d["day"] = pd.to_datetime(d.ts, unit="s").dt.floor("D")
    days = sorted(d.day.unique())
    print(f"{k}. alıcı, {h:g} saatte 2x; gün gün (hepsi):")
    for day in days:
        print(f"  {pd.Timestamp(day):%d %b}: {line(d[d.day == day])}")
    rows, imps = [], []
    for day in days[2:]:  # at least two days to learn from
        tr, te = d[d.day < day], d[d.day == day].copy()
        m = HistGradientBoostingClassifier(**PARAMS).fit(tr[FEATURES], tr.y)
        te["score"] = m.predict_proba(te[FEATURES])[:, 1]
        te["pct"] = te.score.rank(pct=True)
        rows.append(te)
        imp = permutation_importance(m, te[FEATURES], te.y, scoring="roc_auc", n_repeats=3, random_state=0)
        imps.append(imp.importances_mean)
    t = pd.concat(rows)
    print(f"\nWalk-forward ({', '.join(f'{pd.Timestamp(x):%d %b}' for x in days[2:])}; her gün önceki günlerle eğitildi):")
    print(f"  {'hepsi':>10}: {line(t)}")
    n_days = t.day.nunique()
    for top in (0.05, 0.02, 0.01):
        sel = t[t.pct > 1 - top]
        print(f"  {'en iyi %' + format(100 * top, 'g'):>10}: {line(sel)} · günde ~{len(sel) / n_days:.0f}")
    for day, g in t.groupby("day"):
        print(f"  {pd.Timestamp(day):%d %b} en iyi %2: {line(g[g.pct > 0.98])}")
    imp = pd.Series(np.mean(imps, axis=0), index=FEATURES).sort_values(ascending=False)
    print("\nEn etkili kriterler (test günlerinde AUC katkısı):")
    print("  " + " · ".join(f"{c} {v:.3f}" for c, v in imp.head(8).items()))


if __name__ == "__main__":
    main()
