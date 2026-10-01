"""Find the best entry rule on the research table (scripts/research_build.py), honestly.

  python scripts/research_model.py <table.parquet> [<table.parquet> ...]

Time split: train = oldest 60%, valid = next 20%, test = newest 20%. A rule fires at a coin's first matching
moment (then the coin rests 24 h), like the live bot. Scored as $ per $100 trade (3x or out at 60 min, entry
30 s after the signal), with the mean, the mean without the best 5% (luck check) and the median.
"""

import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.tree import DecisionTreeRegressor, export_text

TARGET = "pnl_30_3x"
FEATURES = ["b1", "b5", "prev5", "b10", "b30", "buys5", "sells5", "sellers5", "usd5", "usd10", "sell10", "avg10",
            "whale10", "hold30", "buy_ratio10", "age_min", "runup", "chg5", "fdv", "smart10", "smart_wins10"]
COOLDOWN = 86400


def fires(df: pd.DataFrame, mask: np.ndarray) -> pd.DataFrame:
    """The rows a rule would alert on: the first match per coin, then 24 h of rest for that coin."""
    last: dict = {}
    keep = []
    for idx, coin, t in zip(np.nonzero(mask)[0], df["coin"].values[mask], df["ts"].values[mask]):
        if coin in last and t - last[coin] < COOLDOWN:
            continue
        last[coin] = t
        keep.append(idx)
    return df.iloc[keep]


def score(rows: pd.DataFrame, days: float, col: str = TARGET) -> str:
    v = rows[col].dropna().values
    if len(v) < 5:
        return f"{len(v)} sinyal (az)"
    trimmed = np.sort(v)[: max(1, int(len(v) * 0.95))].mean()
    return (f"{len(v)} sinyal ({len(v) / days:.1f}/gün) · ort {v.mean():+.1f}$ · %5 hariç {trimmed:+.1f}$ · "
            f"medyan {np.median(v):+.1f}$ · kârlı %{100 * (v > 0).mean():.0f} · 3x %{100 * (v > 150).mean():.0f}")


def main():
    df = pd.concat([pd.read_parquet(p) for p in sys.argv[1:]], ignore_index=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df = df[df[TARGET].notna()].reset_index(drop=True)
    n = len(df)
    cut1, cut2 = df["ts"].iloc[int(n * 0.6)], df["ts"].iloc[int(n * 0.8)]
    parts = {"train": df[df.ts < cut1], "valid": df[(df.ts >= cut1) & (df.ts < cut2)], "test": df[df.ts >= cut2]}
    days = {k: (v.ts.max() - v.ts.min()) / 86400 for k, v in parts.items()}
    print(f"{n} an, {df.coin.nunique()} coin, {(df.ts.max() - df.ts.min()) / 86400:.1f} gün · "
          + " · ".join(f"{k} {days[k]:.1f} gün" for k in parts) + "\n")

    def report(title, rule):
        print(title)
        for k, part in parts.items():
            mask = rule(part).values if hasattr(rule(part), "values") else rule(part)
            print(f"   {k:5}: {score(fires(part.reset_index(drop=True), np.asarray(mask)), days[k])}")

    report("Taban: her coinin ilk anı (≥3 alıcı / 5 dk)", lambda p: np.ones(len(p), bool))
    report("Canlı kural A'nın Fomo kısmı (5 dk ≥5, önceki 0, $50+, tutma 0.8)",
           lambda p: (p.b5 >= 5) & (p.prev5 == 0) & (p.avg10 >= 50) & (p.hold30 >= 0.8))
    report("Önceki en iyi Fomo kuralı (≥8 alıcı, önceki 0, $200+, tutma 1, FDV ≤$50k, yaş ≤6s)",
           lambda p: (p.b5 >= 8) & (p.prev5 == 0) & (p.avg10 >= 200) & (p.hold30 >= 1) & (p.fdv <= 50_000)
           & (p.age_min <= 360))

    train = parts["train"]
    y = train[TARGET].clip(-100, 200)
    gbm = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=200,
                                        l2_regularization=1.0, random_state=0)
    gbm.fit(train[FEATURES], y)
    print("\nModel (gradient boosting) puanına göre: en yüksek %X an")
    scores = {k: gbm.predict(v[FEATURES]) for k, v in parts.items()}
    for q in (0.5, 1, 2, 5, 10):
        bar = np.percentile(scores["valid"], 100 - q)
        print(f" puan ≥ {bar:.1f} (valid'in en iyi %{q:g}'i)")
        for k, part in parts.items():
            print(f"   {k:5}: {score(fires(part.reset_index(drop=True), scores[k] >= bar), days[k])}")

    from sklearn.inspection import permutation_importance
    valid = parts["valid"]
    imp = permutation_importance(gbm, valid[FEATURES], valid[TARGET].clip(-100, 200), n_repeats=3, random_state=0)
    order = np.argsort(-imp.importances_mean)
    print("\nÖzellik önemi (valid): " + ", ".join(f"{FEATURES[i]} {imp.importances_mean[i]:.3f}" for i in order[:10]))

    tree = DecisionTreeRegressor(max_depth=4, min_samples_leaf=300, random_state=0).fit(train[FEATURES], y)
    print("\nOkunabilir ağaç (eğitim verisi, yaprak = ortalama $):")
    print(export_text(tree, feature_names=FEATURES, decimals=1))
    leaves = {k: tree.apply(v[FEATURES]) for k, v in parts.items()}
    means = pd.Series(y.values).groupby(leaves["train"]).mean().sort_values(ascending=False)
    print("En iyi 3 yaprak, dönemlere göre:")
    for leaf in means.index[:3]:
        print(f" yaprak {leaf} (eğitim ort. {means[leaf]:+.1f}$)")
        for k, part in parts.items():
            print(f"   {k:5}: {score(fires(part.reset_index(drop=True), leaves[k] == leaf), days[k])}")


if __name__ == "__main__":
    main()
