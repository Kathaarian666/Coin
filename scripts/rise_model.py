"""Which moments lead to doubled money? Analysis of the scripts/rise_build.py table, honestly.

  python scripts/rise_model.py <rise.parquet>

1. What a buy at a random candidate moment gives: how often the money doubles (after fees and slippage), how
   fast, how deep it falls first, and the $ result of "sell at 2x, else after 72 h".
2. Each feature in quintiles: doubling rate and $ per trade (one moment per coin per bin).
3. Walk-forward by day: each test day's trades are picked only with labels that were complete before the day
   began (a 72 h label needs 72 h). A gradient-boosting model (top q% of its score) and the best readable
   rule from a small grid. A coin is bought once (its first matching moment).
"""

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rise_build import value_after  # noqa: E402

FEATURES = ["b1", "b5", "prev5", "b10", "b30", "buys5", "sells5", "sellers5", "usd5", "usd10", "sell10", "avg10",
            "whale10", "hold30", "buy_ratio10", "age_min", "runup", "chg5", "fdv", "smart10", "smart_wins10",
            "buyers_all", "sellers_all", "usd_all", "off_peak", "depth", "depth_known"]
H = 72.0
STOPS = (0.5, 0.6, 0.7, 0.8)
STOP_FILL = 0.9  # a stop in a thin, falling pool fills about 10% under its level
RNG = np.random.default_rng(0)
GRID = {
    "fdv": (15_000, 30_000, 60_000, np.inf),
    "b5": (3, 5, 8, 12),
    "whale10": (0.3, 0.5, 1.0),
    "smart10": (0, 3, 10),
    "age_min": (60, 360, np.inf),
    "runup": (1.5, 3.0, np.inf),
}


def add_stops(df: pd.DataFrame):
    """$ of "sell when the money doubles, cut when the price falls to s x the entry, else sell at 72 h"."""
    for s in STOPS:
        stopped = df["low"].values < s
        cut = np.array([value_after(s * STOP_FILL, d) for d in df["depth"].values])
        df[f"pnl_stop{s:g}"] = np.where(stopped, cut, df["pnl"].values)


def first_per_coin(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("ts").drop_duplicates("coin", keep="first")


def describe(rows: pd.DataFrame, days: float | None = None, col: str = "pnl") -> str:
    if len(rows) < 5:
        return f"{len(rows)} işlem (az)"
    hit = (rows["hit"] & (rows["low"] >= float(col[8:]))) if col.startswith("pnl_stop") else rows["hit"]
    hit, pnl = hit.values, rows[col].values
    by_day = pd.Series(pnl).groupby((rows["ts"].values // 86400).astype(int))
    boots = [np.concatenate([by_day.get_group(d).values for d in RNG.choice(list(by_day.groups), len(by_day))]).mean()
             for _ in range(1000)] if by_day.ngroups > 1 else [pnl.mean()]
    lo, hi = np.percentile(boots, [5, 95])
    rate = f" ({len(rows) / days:.1f}/gün)" if days else ""
    return (f"{len(rows)} işlem{rate} · 2x %{100 * hit.mean():.1f} · ort {pnl.mean():+.1f}$ [GA %90 {lo:+.1f}…{hi:+.1f}]"
            f" · medyan {np.median(pnl):+.1f}$ · artı gün {(by_day.mean() > 0).sum()}/{by_day.ngroups}")


def main():
    df = pd.read_parquet(sys.argv[1]).sort_values("ts").reset_index(drop=True)
    df["day"] = (df["ts"] // 86400).astype(int)
    add_stops(df)
    exits = ["pnl"] + [f"pnl_stop{s:g}" for s in STOPS]
    full = df[df.obs_h >= H - 0.01]
    print(f"{len(df)} an, {df.coin.nunique()} coin · 72 saati tam gözlenen: {len(full)} an "
          f"({pd.to_datetime(full.ts.min(), unit='s'):%d.%m}–{pd.to_datetime(full.ts.max(), unit='s'):%d.%m})\n")

    base = first_per_coin(full)
    hits = base[base.hit]
    print("=== 1. Her coinin ilk aday anında (≥3 alıcı / 5 dk) $100 alsaydım, 72 saat ===")
    print(f"  {describe(base)}")
    print(f"  Gereken fiyat katı (kayma+komisyon): medyan {base.need.median():.2f}x · havuz derinliği medyan "
          f"${base.depth.median():,.0f}")
    for m in (5, 30, 60, 360, 1440, 4320):
        print(f"  {m:>5} dk içinde 2x: %{100 * (base.t_hit <= m).mean():.1f}")
    print(f"  2x yapanlarda önce en dip: medyan {hits.low.median():.2f}x · %25'i {hits.low.quantile(.25):.2f}x'e kadar "
          f"düştü · süre medyan {hits.t_hit.median():.0f} dk")
    for col in exits[1:]:
        print(f"  2x'te sat, {col[8:]}x'te kes: {describe(base, col=col)}")
    miss = base[~base.hit]
    print(f"  2x yapmayanlarda 72 s sonu: medyan {miss.final.median():.2f}x · <0.2x %{100 * (miss.final < .2).mean():.0f}")

    print("\n=== 2. Özellik dilimleri (her dilimde coin başına ilk an, 72 s tam gözlenen) ===")
    for col in FEATURES:
        v = full[col]
        if v.nunique() < 3:
            continue
        try:
            q = pd.qcut(v, 5, duplicates="drop")
        except ValueError:
            continue
        parts = []
        for b in q.cat.categories:
            g = first_per_coin(full[q == b])
            parts.append(f"{b.left:.3g}–{b.right:.3g}: %{100 * g.hit.mean():.0f} {g.pnl.mean():+.0f}$")
        print(f"  {col:12} " + " | ".join(parts))

    print("\n=== 3. Gün gün örnek dışı (karar sadece etiketi kesinleşmiş geçmişle) ===")
    days = sorted(full.day.unique())
    test_days = [d for d in days if (full.ts < d * 86400 - H * 3600).sum() > 20000]
    print(f"  test günleri: {len(test_days)} ({', '.join(pd.to_datetime(d * 86400, unit='s').strftime('%d.%m') for d in test_days)})")
    keys = list(GRID)
    rules = [dict(zip(keys, c)) for c in itertools.product(*GRID.values())]
    cols = {k: full[k].fillna(np.inf if k == "fdv" else 0).values for k in keys}
    masks = [np.all([cols[k] >= r[k] if k in ("b5", "smart10") else cols[k] <= r[k] for k in keys], axis=0)
             for r in rules]
    picks = {"taban": [], "model %1": [], "model %3": [], "model %10": [], "kural": []}
    for d in test_days:
        start = d * 86400
        past = (full.ts < start - H * 3600).values
        today = (full.day == d).values
        picks["taban"].append(first_per_coin(full[today]))
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                             min_samples_leaf=200, l2_regularization=1.0, random_state=0)
        clf.fit(full.loc[past, FEATURES], full.loc[past, "hit"])
        recent = past & (full.ts >= start - H * 3600 - 2 * 86400).values
        s_recent = clf.predict_proba(full.loc[recent, FEATURES])[:, 1]
        s_today = clf.predict_proba(full.loc[today, FEATURES])[:, 1]
        for q in (1, 3, 10):
            bar = np.percentile(s_recent, 100 - q)
            picks[f"model %{q}"].append(first_per_coin(full[today][s_today >= bar]))
        best, best_lb = None, -np.inf
        for k, m in enumerate(masks):
            g = first_per_coin(full[past & m])
            if len(g) < 50:
                continue
            for col in exits:
                lb = g[col].mean() - g[col].std() / np.sqrt(len(g))
                if lb > best_lb:
                    best, best_lb = (k, col), lb
        if best is not None:
            g = first_per_coin(full[today & masks[best[0]]])
            picks["kural"].append(g.assign(pnl_chosen=g[best[1]]))
            r = rules[best[0]]
            print(f"  {pd.to_datetime(start, unit='s'):%d.%m}: kural FDV≤{r['fdv']:.0f} · 5dk alıcı≥{r['b5']} · balina≤{r['whale10']}"
                  f" · akıllı≥{r['smart10']} · yaş≤{r['age_min']} dk · ilk fiyattan≤{r['runup']}x · çıkış {best[1]} (geçmiş alt {best_lb:+.1f}$)")
    n_days = len(test_days)
    for name, p in picks.items():
        rows = pd.concat(p) if p else full.iloc[:0]
        if name == "kural":
            print(f"  {name:10} (her gün geçmişte en iyi kural + çıkış): {describe(rows.assign(pnl=rows.pnl_chosen), n_days)}")
            continue
        for col in exits:
            print(f"  {name:10} {col:13}: {describe(rows, n_days, col)}")


if __name__ == "__main__":
    main()
