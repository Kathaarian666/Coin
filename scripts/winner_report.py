"""Compare later winners with the rest at each checkpoint (scripts/winner_study.py table).

  python scripts/winner_report.py <winners.parquet> [<multiple>=10]
"""

import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.tree import DecisionTreeClassifier, export_text

FEATURES = ["mins_to_k", "trades_to_k", "usd_all", "usd_per_trade", "max_buy", "top_buyer_share", "repeat_buys",
            "sellers", "early_sold", "sell_usd_share", "buyers_5m", "buyers_prev5m", "usd_10m", "fresh_share", "smart",
            "runup", "off_high", "fdv", "is_pons", "launch_age_min", "launcher_prior", "market_buyers_1h"]


def main():
    df = pd.read_parquet(sys.argv[1])
    win = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    df["win"] = df.peak >= win
    split = df.ts.quantile(0.65)
    for k, g in df.groupby("k"):
        print(f"\n===== {k}. alıcı anı: {len(g)} coin · sonra ≥{win:g}x: %{100 * g.win.mean():.1f} ({g.win.sum()}) · "
              f"≥2x %{100 * (g.peak >= 2).mean():.0f} · ≥5x %{100 * (g.peak >= 5).mean():.0f} =====")
        w, rest = g[g.win], g[g.peak < 2]
        print(f"  {'özellik':17} {'kazanan medyan':>15} {'<2x medyan':>11}   en iyi beşte birlik dilimde ≥{win:g}x oranı")
        for f in FEATURES:
            v = g[f].astype(float)
            if v.nunique() < 3:
                continue
            q = pd.qcut(v.rank(method="first"), 5, labels=False)
            rates = g.win.groupby(q).mean()
            lo_hi = f"{v[q == rates.idxmax()].min():.3g}–{v[q == rates.idxmax()].max():.3g}"
            print(f"  {f:17} {w[f].astype(float).median():15.3g} {rest[f].astype(float).median():11.3g}   "
                  f"%{100 * rates.max():.0f} ({lo_hi}) vs en kötü %{100 * rates.min():.0f}")
        tr, te = g[g.ts < split], g[g.ts >= split]
        if te.win.sum() < 10:
            continue
        gbm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, min_samples_leaf=40, random_state=0)
        gbm.fit(tr[FEATURES].astype(float), tr.win)
        s = gbm.predict_proba(te[FEATURES].astype(float))[:, 1]
        print(f"  model (eğitim ilk %65, test son %35): test AUC {roc_auc_score(te.win, s):.3f}")
        for q in (5, 10, 20):
            top = te[s >= np.percentile(s, 100 - q)]
            print(f"    en yüksek puanlı %{q}: {len(top)} coin · ≥{win:g}x %{100 * top.win.mean():.1f} "
                  f"(taban %{100 * te.win.mean():.1f}) · yakalanan kazanan {top.win.sum()}/{te.win.sum()}")
        tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=max(30, len(tr) // 40), random_state=0)
        tree.fit(tr[FEATURES].astype(float).fillna(-1), tr.win)
        leaves_tr = tree.apply(tr[FEATURES].astype(float).fillna(-1))
        leaves_te = tree.apply(te[FEATURES].astype(float).fillna(-1))
        best = pd.Series(tr.win.values).groupby(leaves_tr).mean().sort_values(ascending=False)
        print("  okunur ağaç (eğitim):\n" + "\n".join("    " + l for l in export_text(tree, feature_names=FEATURES, decimals=2).splitlines()))
        for leaf in best.index[:2]:
            m_te = leaves_te == leaf
            print(f"    yaprak {leaf}: eğitim ≥{win:g}x %{100 * best[leaf]:.1f} ({(leaves_tr == leaf).sum()}) → test "
                  f"%{100 * te.win[m_te].mean() if m_te.any() else 0:.1f} ({m_te.sum()})")


if __name__ == "__main__":
    main()
