"""Walk-forward check of the research findings: is the edge real day after day, and does a simple rule keep it?

  python scripts/research_robust.py <table.parquet> [<table.parquet> ...]

Each UTC day from the 6th day of data on is a test day. Everything is decided only from the days before it
(2 h gap, so no outcome reaches into the test day):
  * model: gradient boosting trained on the past, the test day's alerts are its top q% (bar = percentile of
    the model's scores on the last 2 training days, so the rate is known before the day starts);
  * rule: from a small grid of readable rules, the one with the best past lower bound (mean - 1 SE, at least
    40 past signals) is picked each day and traded the next day.
A rule fires at a coin's first matching moment, then the coin rests 24 h. $ per $100 trade, 3x or out at
60 min, entry 30 s after the signal, multiples capped at 3x (the hour-end price has rare data spikes).
The out-of-sample trades of all test days are pooled; the 90% interval is a bootstrap over whole days.
"""

import itertools
import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from research_model import FEATURES  # noqa: E402

TARGET = "pnl_30_3x"
CAP = (-100.0, 199.0)  # 3x on $100 minus the fee
COOLDOWN = 86400
GAP = 7200
MIN_TRAIN_DAYS = 5
MIN_PAST = 40
RNG = np.random.default_rng(0)

GRID = {
    "smart10": (0, 2, 3, 5, 7, 10),
    "fdv": (20_000, 30_000, 50_000, 100_000, np.inf),
    "b5": (3, 5, 8, 12),
    "whale10": (0.3, 0.4, 0.5, 1.0),
    "hold30": (0.0, 0.8),
}


def fires(coin: np.ndarray, ts: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Indices (into the time-sorted table) a rule alerts on: first match per coin, then 24 h of rest."""
    last: dict = {}
    keep = []
    for idx in np.nonzero(mask)[0]:
        c, t = coin[idx], ts[idx]
        if c in last and t - last[c] < COOLDOWN:
            continue
        last[c] = t
        keep.append(idx)
    return np.asarray(keep, dtype=int)


def summary(pnl: np.ndarray, day: np.ndarray, n_days: int) -> str:
    if len(pnl) < 5:
        return f"{len(pnl)} sinyal (az)"
    days = np.unique(day)
    by_day = {d: pnl[day == d] for d in days}
    boots = []
    for _ in range(2000):
        pick = RNG.choice(days, len(days))
        v = np.concatenate([by_day[d] for d in pick])
        boots.append(v.mean())
    lo, hi = np.percentile(boots, [5, 95])
    day_means = [by_day[d].mean() for d in days]
    pos_days = sum(m > 0 for m in day_means)
    return (f"{len(pnl)} sinyal ({len(pnl) / n_days:.1f}/gün) · ort {pnl.mean():+.1f}$ [GA %90 {lo:+.1f}…{hi:+.1f}] · "
            f"medyan {np.median(pnl):+.1f}$ · kârlı %{100 * (pnl > 0).mean():.0f} · 3x %{100 * (pnl > 150).mean():.0f}"
            f" · artı gün {pos_days}/{len(days)}")


def rule_text(r: dict) -> str:
    parts = []
    if r["smart10"]:
        parts.append(f"akıllı≥{r['smart10']}")
    if np.isfinite(r["fdv"]):
        parts.append(f"FDV≤${r['fdv'] / 1000:.0f}k")
    parts.append(f"5dk alıcı≥{r['b5']}")
    if r["whale10"] < 1:
        parts.append(f"balina≤{r['whale10']}")
    if r["hold30"]:
        parts.append(f"tutma≥{r['hold30']}")
    return " · ".join(parts)


def main():
    t0 = time.time()
    df = pd.concat([pd.read_parquet(p) for p in sys.argv[1:]], ignore_index=True)
    df = df[df[TARGET].notna()].sort_values("ts").reset_index(drop=True)
    df["y"] = df[TARGET].clip(*CAP)
    df["day"] = (df["ts"] // 86400).astype(int)
    coin = df["coin"].cat.codes.values if hasattr(df["coin"], "cat") else pd.factorize(df["coin"])[0]
    ts, y, day = df["ts"].values, df["y"].values, df["day"].values
    days = np.unique(day)
    test_days = days[MIN_TRAIN_DAYS:]
    print(f"{len(df)} an, {df.coin.nunique()} coin, {len(days)} gün veri · test günleri {len(test_days)} "
          f"({pd.to_datetime(test_days[0] * 86400, unit='s').date()} → "
          f"{pd.to_datetime(test_days[-1] * 86400, unit='s').date()})\n")

    def pooled(title, picks):
        idx = np.concatenate(picks) if picks else np.array([], int)
        print(f"{title}\n   {summary(y[idx], day[idx], len(test_days))}")
        return idx

    # baselines over the test days
    base = fires(coin, ts, np.ones(len(df), bool))
    pooled("Taban: her coinin ilk anı", [base[np.isin(day[base], test_days)]])
    live_a = fires(coin, ts, ((df.b5 >= 5) & (df.prev5 == 0) & (df.avg10 >= 50) & (df.hold30 >= 0.8)).values)
    pooled("Canlı kural A'nın Fomo kısmı", [live_a[np.isin(day[live_a], test_days)]])

    # readable rules: fire each once over the whole table, then score by day
    keys = list(GRID)
    rules = [dict(zip(keys, combo)) for combo in itertools.product(*GRID.values())]
    cols = {k: df[k].fillna(np.inf if k == "fdv" else 0).values for k in keys}
    fired = []
    for r in rules:
        mask = ((cols["smart10"] >= r["smart10"]) & (cols["fdv"] <= r["fdv"]) & (cols["b5"] >= r["b5"])
                & (cols["whale10"] <= r["whale10"]) & (cols["hold30"] >= r["hold30"]))
        fired.append(fires(coin, ts, mask))
    print(f"\n{len(rules)} kural hazır ({time.time() - t0:.0f} sn)")

    model_picks = {q: [] for q in (0.5, 1, 2, 5)}
    rule_picks, chosen = [], []
    for d in test_days:
        start = d * 86400
        past = ts < start - GAP
        # rule chosen on the past only
        best, best_lb = None, -np.inf
        for k, f in enumerate(fired):
            v = y[f[ts[f] < start - GAP]]
            if len(v) < MIN_PAST:
                continue
            lb = v.mean() - v.std(ddof=1) / np.sqrt(len(v))
            if lb > best_lb:
                best, best_lb = k, lb
        if best is not None:
            f = fired[best]
            rule_picks.append(f[day[f] == d])
            chosen.append((d, best, best_lb))
        # model trained on the past only
        gbm = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                            min_samples_leaf=200, l2_regularization=1.0, random_state=0)
        gbm.fit(df.loc[past, FEATURES], y[past])
        recent = past & (ts >= start - 2 * 86400 - GAP)
        today = day == d
        s_recent, s_today = gbm.predict(df.loc[recent, FEATURES]), gbm.predict(df.loc[today, FEATURES])
        for q in model_picks:
            mask = np.zeros(len(df), bool)
            mask[np.nonzero(today)[0]] = s_today >= np.percentile(s_recent, 100 - q)
            model_picks[q].append(fires(coin, ts, mask))
        print(f"  {pd.to_datetime(start, unit='s').date()}: kural {rule_text(rules[best]) if best is not None else '-'}"
              f" (geçmiş alt sınır {best_lb:+.1f}$) · {time.time() - t0:.0f} sn", flush=True)

    print("\n=== Örnek dışı (her gün sadece geçmişle karar) ===")
    for q, picks in model_picks.items():
        pooled(f"Model en iyi %{q:g}", picks)
    pooled("Her gün geçmişte en iyi sade kural", rule_picks)

    print("\n=== Sabit sade kurallar, test günleri boyunca (seçim tüm veriye bakılarak: iyimser) ===")
    table = []
    for k, f in enumerate(fired):
        f = f[np.isin(day[f], test_days)]
        if len(f) < 60:
            continue
        v = y[f]
        day_means = pd.Series(v).groupby(day[f]).mean()
        table.append((v.mean() - v.std(ddof=1) / np.sqrt(len(v)), k, len(v), v.mean(), (day_means > 0).mean()))
    table.sort(reverse=True)
    for lb, k, n, mean, pos in table[:15]:
        print(f"  {rule_text(rules[k]):55} {n:4} sinyal · ort {mean:+.1f}$ · alt {lb:+.1f}$ · artı gün %{100 * pos:.0f}")
    counts = pd.Series([rules[k]["smart10"] for _, k, _ in chosen]).value_counts()
    print("\nGünlük seçilen kuralların akıllı cüzdan eşiği: " + ", ".join(f"≥{a}: {b} gün" for a, b in counts.items()))


if __name__ == "__main__":
    main()
