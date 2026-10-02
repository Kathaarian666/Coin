"""Can the k-th on-chain (curve) buyer moment tell serious risers? Report on scripts/curve_study.py's table.

  python scripts/curve_report.py <curve_cp.parquet>
"""

import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

FEATURES = ["mins_from_launch", "buys", "eth_all", "eth_per_buy", "max_buy_eth", "top_buyer_share", "repeat_buys",
            "sellers", "sell_eth_share", "buyers_1m", "buyers_prev1m", "snipe_share", "dev_bought", "dev_sold",
            "curve_sold_pct", "runup", "mcap_usd", "fomo_buys_before", "launcher_prior"]
TIERS = (2, 5, 10, 50, 100)


def dist(peak):
    return " · ".join(f"≥{t}x %{100 * (peak >= t).mean():.1f}" for t in TIERS) + f" · medyan {peak.median():.2f}x"


def main():
    df = pd.read_parquet(sys.argv[1])
    df[FEATURES] = df[FEATURES].astype(float)
    split = df.ts.quantile(0.65)
    for k, g in df.groupby("k"):
        print(f"\n===== zincirde {k}. alıcı · {len(g)} coin · lansmandan medyan {g.mins_from_launch.median():.1f} dk · "
              f"o ana kadar Fomo alımı medyan {g.fomo_buys_before.median():.0f} · mcap medyan ${g.mcap_usd.median():,.0f} =====")
        print(f"  hepsi: {dist(g.peak)}")
        w, rest = g[g.peak >= 5], g[g.peak < 2]
        print("  özellik (≥5x olanlar medyan / <2x medyan):")
        for c in FEATURES:
            print(f"    {c:17} {w[c].median():10.3g} / {rest[c].median():10.3g}")
        tr, te = g[g.ts < split], g[g.ts >= split]
        gbm = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.04, min_samples_leaf=40,
                                             l2_regularization=1.0, random_state=0).fit(tr[FEATURES], tr.peak >= 5)
        s = gbm.predict_proba(te[FEATURES])[:, 1]
        print(f"  model test AUC (≥5x) {roc_auc_score(te.peak >= 5, s):.3f}")
        for q in (5, 10, 20):
            top = te[s >= np.percentile(s, 100 - q)]
            print(f"    en iyi %{q:<2} ({len(top):3} coin): {dist(top.peak)}")
        print(f"    test hepsi ({len(te)} coin): {dist(te.peak)}")
        imp = permutation_importance(gbm, te[FEATURES], te.peak >= 5, n_repeats=5, random_state=0, scoring="roc_auc")
        order = np.argsort(-imp.importances_mean)[:8]
        print("    en etkili: " + ", ".join(f"{FEATURES[i]} {imp.importances_mean[i]:+.3f}" for i in order))


if __name__ == "__main__":
    main()
