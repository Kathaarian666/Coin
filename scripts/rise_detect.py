"""Can we tell, at the k-th buyer, which coins will rise seriously (2x / 5x / 10x / 50x / 100x)?

  python scripts/rise_detect.py <winners_with_transfers.parquet>

Per checkpoint: how winners (>= 5x later) differ from the rest on every feature (Fomo flow + holders from the
Transfer logs), then a gradient-boosting score trained on the first 65% of the period and judged on the last
35%: the rise distribution of its top 5 / 10 / 20% against all coins.
"""

import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

FLOW = ["mins_to_k", "trades_to_k", "usd_all", "usd_per_trade", "max_buy", "top_buyer_share", "repeat_buys",
        "sellers", "early_sold", "sell_usd_share", "buyers_5m", "buyers_prev5m", "usd_10m", "fresh_share", "smart",
        "runup", "off_high", "fdv", "is_pons", "launch_age_min", "launcher_prior", "market_buyers_1h"]
HOLD = ["holders", "holder_growth_10m", "top10_pct", "top1_pct", "dev_pct", "dev_sent_pct", "sniper_pct",
        "fomo_holder_share", "transfers_10m"]
TIERS = (2, 5, 10, 50, 100)


def dist(peak: pd.Series) -> str:
    return " · ".join(f"≥{t}x %{100 * (peak >= t).mean():.1f}" for t in TIERS) + f" · medyan {peak.median():.2f}x"


def main():
    df = pd.read_parquet(sys.argv[1])
    feats = FLOW + [c for c in HOLD if c in df]
    df[feats] = df[feats].astype(float)
    split = df.ts.quantile(0.65)
    for k, g in df.groupby("k"):
        print(f"\n===== {k}. alıcı anı · {len(g)} coin =====\n  hepsi: {dist(g.peak)}")
        w, rest = g[g.peak >= 5], g[g.peak < 2]
        print("  holder özellikleri (≥5x olanlar medyan / <2x medyan):")
        for c in HOLD:
            if c in g:
                print(f"    {c:18} {w[c].median():9.3g} / {rest[c].median():9.3g}")
        tr, te = g[g.ts < split], g[g.ts >= split]
        for name, cols in (("sadece Fomo akışı", FLOW), ("akış + holder", feats)):
            gbm = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.04, min_samples_leaf=40,
                                                 l2_regularization=1.0, random_state=0)
            gbm.fit(tr[cols], tr.peak >= 5)
            s = gbm.predict_proba(te[cols])[:, 1]
            print(f"  model [{name}] test AUC (≥5x) {roc_auc_score(te.peak >= 5, s):.3f}")
            for q in (5, 10, 20):
                top = te[s >= np.percentile(s, 100 - q)]
                print(f"    en iyi %{q:<2} ({len(top):3} coin): {dist(top.peak)}")
        print(f"    test hepsi ({len(te)} coin): {dist(te.peak)}")
        imp = permutation_importance(gbm, te[feats], te.peak >= 5, n_repeats=5, random_state=0, scoring="roc_auc")
        order = np.argsort(-imp.importances_mean)[:8]
        print("    en etkili özellikler: " + ", ".join(f"{feats[i]} {imp.importances_mean[i]:+.3f}" for i in order))


if __name__ == "__main__":
    main()
