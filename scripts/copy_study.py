"""Copy-trading study: do Fomo wallets that made money for a copier keep doing it?

  python scripts/copy_study.py <trades.db or events.parquet> [<events out.parquet>] [<picks out.parquet>]

Every wallet's first buy in each coin is an event. A copier buys $100 30 s later at the pool price then (the last
buy's price marked up for its impact, plus our slippage from the pool depth of the last 15 minutes; a coin
nobody buys again is still bought) and exits by each rule in EXITS (target = the money
multiplied by that much after fees and slippage, stop = price falls to that multiple of the entry, else sold
at the time limit). The copy result of an event is known once its time limit has passed.

Walk-forward by day: a wallet is "followed" on a test day if its copies that finished before the day had
at least N results averaging at least M dollars. On the test day the first buy of a followed wallet in a coin
is copied (one trade per coin). N, M and the exit are chosen each day from the past days only.
"""

import bisect
import itertools
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rise_build import (DELAY, POSITION, Sparse, buy_series, depth_at, depth_prefix, load, needed,  # noqa: E402
                        segments, value_after)

# name: (target money multiple or None, stop price multiple or None, time limit in minutes)
EXITS = {
    "2x/60dk": (2.0, None, 60),
    "2x/6s": (2.0, None, 360),
    "2x/0.7stop/24s": (2.0, 0.7, 1440),
    "2x/72s": (2.0, None, 4320),
    "1.5x/30dk": (1.5, None, 30),
    "3x/0.7stop/24s": (3.0, 0.7, 1440),
}
STOP_FILL = 0.9
RNG = np.random.default_rng(0)


def first_at_most(tab: Sparse, lo: int, x: float) -> int:
    n, pos = len(tab.levels[0]), lo
    for lvl in range(len(tab.levels) - 1, -1, -1):
        if pos + (1 << lvl) <= n and tab.levels[lvl][pos] > x:
            pos += 1 << lvl
    return pos


def copy_result(c, t_buy, depth, seg_end, rule):
    """$ result of buying $100 at t_buy and exiting by `rule`. Nothing after t_buy is needed to enter: the entry
    is the pool price left by the last buys before t_buy (median of the last 3 fills, against single bad prints,
    marked up for the last buy's own impact). A price that never held the target for two buys in a row is capped
    at the target (a lone print above it is a data error or a spike nobody could sell into)."""
    bts, bpx, busd, hmax, pmin = c
    target, stop, minutes = rule
    e = bisect.bisect_right(bts, t_buy) - 1
    p_in = float(np.median(bpx[max(0, e - 2):e + 1])) * (1 + 1.5 * busd[e] / depth)
    end = min(t_buy + minutes * 60, seg_end)
    last = bisect.bisect_right(bts, end) - 1
    nxt = e + 1
    need = needed(round(depth, -2), target)
    k_hit = hmax.first_at_least(nxt, need * p_in) + 1 if nxt < len(bts) - 1 else len(bts)
    k_stop = first_at_most(pmin, nxt, stop * p_in) if stop and nxt < len(bts) else len(bts)
    if k_hit <= last and k_hit < k_stop:
        return (target - 1) * POSITION
    if k_stop <= last:
        return value_after(stop * STOP_FILL, depth)
    lo = max(bisect.bisect_left(bts, end - 600), nxt)
    final = float(np.median(bpx[lo:last + 1])) / p_in if lo <= last else bpx[last] / p_in
    return value_after(min(final, need), depth)


def build(path):
    t0 = time.time()
    coins, _ = load(path)
    segs = segments(np.array([r[0] for rows in coins.values() for r in rows[::20]]))
    seg_starts = [s for s, _ in segs]
    events = []
    for n, (coin, rows) in enumerate(coins.items()):
        bts, bpx, busd, who = buy_series(rows)
        if len(bpx) < 3:
            continue
        c = (bts, bpx, busd, Sparse(np.minimum(bpx[:-1], bpx[1:]), np.maximum), Sparse(bpx, np.minimum))
        pref = depth_prefix(bts, bpx, busd)
        seen = set()
        for k, w in enumerate(who):
            if w in seen:
                continue
            seen.add(w)
            t = bts[k]
            seg_end = segs[bisect.bisect_right(seg_starts, t) - 1][1]
            depth, depth_known = depth_at(pref, t)
            row = {"wallet": w, "coin": coin, "ts": t, "rank": len(seen), "usd": busd[k], "depth": depth,
                   "depth_known": depth_known, "coin_buyers": len(set(who)),
                   "obs_min": (seg_end - t - DELAY) / 60}
            for name, rule in EXITS.items():
                row[name] = copy_result(c, t + DELAY, depth, seg_end, rule)
            events.append(row)
        if n % 5000 == 0:
            print(f"{n}/{len(coins)} coin · {len(events)} olay · {time.time() - t0:.0f} sn", flush=True)
    df = pd.DataFrame.from_records(events)
    df["coin"] = df["coin"].astype("category")
    return df


def describe(v: np.ndarray, day: np.ndarray, n_days: int) -> str:
    if len(v) < 5:
        return f"{len(v)} işlem (az)"
    days = np.unique(day)
    groups = {d: v[day == d] for d in days}
    boots = [np.concatenate([groups[d] for d in RNG.choice(days, len(days))]).mean() for _ in range(1000)]
    lo, hi = np.percentile(boots, [5, 95])
    pos = sum(groups[d].mean() > 0 for d in days)
    return (f"{len(v)} işlem ({len(v) / n_days:.1f}/gün) · ort {v.mean():+.1f}$ [GA %90 {lo:+.1f}…{hi:+.1f}] · "
            f"medyan {np.median(v):+.1f}$ · kârlı %{100 * (v > 0).mean():.0f} · artı gün {pos}/{len(days)}")


def walk_forward(df: pd.DataFrame):
    df = df.sort_values("ts").reset_index(drop=True)
    df["day"] = (df.ts // 86400).astype(int)
    days = sorted(df.day.unique())
    test_days = [d for d in days if d * 86400 > df.ts.min() + 4 * 86400 and (df.day == d).sum() > 1000]
    print(f"{len(df):,} kopya olayı · {df.wallet.nunique():,} cüzdan · test günleri {len(test_days)}\n")

    print("Taban (her coinde ilk Fomo alıcısından 30 sn sonra gir):")
    first = df[df["rank"] == 1]
    for name in EXITS:
        m = first[np.isin(first.day, test_days) & (first.obs_min >= EXITS[name][2])]
        print(f"  {name:15} {describe(m[name].values, m.day.values, len(test_days))}")

    print("\nKalıcılık: cüzdanların ilk yarıdaki kopya ort. ile ikinci yarıdaki (≥10 olay her yarıda), 2x/60dk:")
    mid = df.ts.quantile(0.5)
    a = df[df.ts < mid].groupby("wallet")["2x/60dk"].agg(["mean", "size"])
    b = df[df.ts >= mid].groupby("wallet")["2x/60dk"].agg(["mean", "size"])
    ab = a.join(b, lsuffix="_a", rsuffix="_b").dropna()
    ab = ab[(ab.size_a >= 10) & (ab.size_b >= 10)]
    ab["q"] = pd.qcut(ab.mean_a, 5, labels=False, duplicates="drop")
    print(f"  {len(ab)} cüzdan · sıra korelasyonu {ab.mean_a.corr(ab.mean_b, method='spearman'):.3f}")
    for q, g in ab.groupby("q"):
        print(f"  ilk yarı dilim {q + 1}: ilk ort {g.mean_a.mean():+.1f}$ → ikinci yarı {g.mean_b.mean():+.1f}$ "
              f"({len(g)} cüzdan, olay ağırlıklı {np.average(g.mean_b, weights=g.size_b):+.1f}$)")

    print("\nGün gün takip (cüzdan seçimi ve çıkış her gün sadece geçmişle):")
    combos = list(itertools.product((5, 10, 20), (0, 10, 20, 40), EXITS))
    picks, chosen, skills = [], [], {}
    for d in test_days:
        start = d * 86400

        def follow(n_min, m_min, name, lo, hi):
            """Copies of followed wallets in [lo, hi): skill from results known before lo."""
            if (lo, name) not in skills:
                known = df[(df.ts + df.obs_min.clip(upper=EXITS[name][2]) * 60 + DELAY < lo)]
                skills[(lo, name)] = known.groupby("wallet")[name].agg(["mean", "size"])
            skill = skills[(lo, name)]
            good = skill[(skill["size"] >= n_min) & (skill["mean"] >= m_min)].index
            today = df[(df.ts >= lo) & (df.ts < hi) & df.wallet.isin(good)]
            return today.drop_duplicates("coin", keep="first")

        best, best_lb = None, -np.inf
        for n_min, m_min, name in combos:
            # score each setting on the 2 days before, each judged with skill known before that day
            past = pd.concat([follow(n_min, m_min, name, start - k * 86400, start - (k - 1) * 86400)
                              for k in (3, 2)])
            past = past[past.ts + EXITS[name][2] * 60 < start]
            if len(past) < 30:
                continue
            v = past[name].values
            lb = v.mean() - v.std() / np.sqrt(len(v))
            if lb > best_lb:
                best, best_lb = (n_min, m_min, name), lb
        if best is None:
            continue
        today = follow(*best, start, start + 86400)
        today = today[today.obs_min >= EXITS[best[2]][2]]
        picks.append(today.assign(pnl=today[best[2]]))
        chosen.append(best)
        print(f"  {pd.to_datetime(start, unit='s'):%d.%m}: ≥{best[0]} kopya, ort ≥${best[1]}, çıkış {best[2]} "
              f"(geçmiş alt {best_lb:+.1f}$) → bugün {len(today)} işlem, ort {today[best[2]].mean():+.1f}$")
    if not picks:
        return None
    p = pd.concat(picks)
    print(f"\n  TOPLAM: {describe(p.pnl.values, p.day.values, len(test_days))}")
    return p


def main():
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = build(path)
        if out:
            df.to_parquet(out)
    picks = walk_forward(df)
    if picks is not None and len(sys.argv) > 3:
        picks.to_parquet(sys.argv[3])


if __name__ == "__main__":
    main()
