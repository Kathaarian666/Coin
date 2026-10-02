"""Second-wave alert moments (PROJE.md §4.4, angle C): a coin at least an hour old wakes up after a quiet spell.

  python scripts/wave_study.py <trades.db> <winners.parquet> <out.parquet>

Moment: a buy at which the coin (first Fomo trade >= 1 h ago) has >= MIN_BUYERS distinct buyers in the last 5 min
and at most 1 in the 30 min before those 5; at most one moment per coin every 6 h. Everything is computed from
trades up to the moment; the label is the plan's 2x (two buys in a row at >= 2x the moment's last buy price, no time
limit). Columns reuse the names of scripts/winner_study.py where the meaning carries over (k = 0), so
scripts/profit_study.py and rise_study.py run on it unchanged:
mins_to_k = minutes since the quiet spell ended · trades_to_k / usd_all / usd_per_trade / max_buy / sellers /
sell_usd_share / same_block_buys / small_buy_share / buyers_5m = the burst (last 5 min) · usd_10m · buyers_60s,
usd_60s_share · runup = price now / price when the burst began · off_high = price now / highest price held so far ·
fdv · launch_age_min = minutes since the coin's first Fomo trade · depth_usd · buyers_hit_rate = the burst's first 3
buyers' earlier record as first buyers of new coins (winners.parquet k = 3, outcome known 1 h after each).
"""

import bisect
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_extra import depth_at  # noqa: E402

START = pd.Timestamp("2026-09-03").value / 1e9
MIN_BUYERS = 5
COOLDOWN = 6 * 3600


def buyer_book(winners):
    """wallet -> (known times, cumulative hits) from the k = 3 moments: outcome known 1 h after the moment."""
    w = pd.read_parquet(winners, columns=["k", "ts", "t2x_h", "first3"])
    w = w[w.k == 3]
    ev = defaultdict(list)
    for t, h, f in zip(w.ts.values + 3600, (w.t2x_h.fillna(99) <= 1).values, w.first3.fillna("").values):
        for x in f.split(","):
            if x:
                ev[x].append((t, int(h)))
    book = {}
    for x, lst in ev.items():
        lst.sort()
        book[x] = ([t for t, _ in lst], np.cumsum([h for _, h in lst]))
    return book


def main():
    t_start = time.time()
    db = sqlite3.connect(sys.argv[1], timeout=300)
    book = buyer_book(sys.argv[2])
    names = {i: a.lower() for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    supply = {a.lower(): r for a, r in db.execute("SELECT addr, raw FROM supply") if r}
    tr = pd.read_sql("SELECT block, ts, token, side, trader, usd, amount FROM trades ORDER BY token, ts", db)
    data_end = tr.ts.max()
    print(f"{len(tr):,} işlem ({time.time() - t_start:.0f} sn)", flush=True)
    rows = []
    for tok, g in tr.groupby("token", sort=False):
        if g.ts.iloc[0] < START or len(g) < 20:
            continue
        ts, side, who, blk = g.ts.values, g.side.values, g.trader.values, g.block.values
        usd = g.usd.fillna(0).values
        px = np.where((g.usd > 0) & (g.amount > 0), g.usd / g.amount.replace(0, np.nan), np.nan)
        buy = (side == 1) & ~np.isnan(px)
        bidx = np.nonzero(buy)[0]
        if len(bidx) < 10:
            continue
        bts, bpx, busd = ts[bidx], px[bidx], usd[bidx]
        held = np.minimum(bpx[:-1], bpx[1:])
        first = ts[0]
        last_moment = -np.inf
        for j in range(len(bidx)):
            i = bidx[j]
            t = ts[i]
            if t - first < 3600 or t - last_moment < COOLDOWN:
                continue
            b5 = np.searchsorted(bts, t - 300, side="right")
            b35 = np.searchsorted(bts, t - 2100, side="right")
            if j + 1 - b5 < MIN_BUYERS or b5 - b35 > 20:  # cheap counts first: too few buys now, or a busy "quiet" spell
                continue
            lo5 = np.searchsorted(ts, t - 300, side="right")
            burst = slice(lo5, i + 1)
            b_burst = side[burst] == 1
            buyers = set(who[burst][b_burst])
            if len(buyers) < MIN_BUYERS:
                continue
            lo35 = np.searchsorted(ts, t - 2100, side="right")
            quiet = slice(lo35, lo5)
            if len(set(who[quiet][side[quiet] == 1])) > 1:
                continue
            last_moment = t
            nb = j + 1  # buys up to now
            p_now = float(bpx[nb - 1])
            hit = np.flatnonzero(held[nb:] >= 2 * p_now)
            bu = usd[burst][b_burst]
            bw = who[burst][b_burst]
            first3 = list(dict.fromkeys(bw))[:3]
            hits = n = 0
            for x in first3:
                kt = book.get(str(x))
                if kt:
                    c = bisect.bisect_right(kt[0], t)
                    n += c
                    hits += int(kt[1][c - 1]) if c else 0
            w10 = ts[:i + 1] > t - 600
            w1 = (ts[burst] > t - 60) & b_burst
            past_held = held[:max(1, nb - 1)]
            rows.append({
                "coin": names[tok], "k": 0, "ts": t,
                "t2x_h": (bts[nb + hit[0] + 1] - t) / 3600 if len(hit) else np.nan,
                "obs_h": (data_end - t) / 3600,
                "peak": np.nan,
                "mins_to_k": (t - ts[lo5]) / 60,
                "trades_to_k": int(b_burst.sum()),
                "usd_all": float(bu.sum()),
                "usd_per_trade": float(bu.mean()),
                "max_buy": float(bu.max()),
                "sellers": len(set(who[burst][side[burst] == 0])),
                "sell_usd_share": float(usd[burst][side[burst] == 0].sum() / max(1.0, usd[burst].sum())),
                "same_block_buys": int(pd.Series(blk[burst][b_burst]).duplicated(keep=False).sum()),
                "small_buy_share": float(np.mean(bu < 20)),
                "buyers_5m": len(buyers),
                "usd_10m": float(usd[:i + 1][w10 & (side[:i + 1] == 1)].sum()),
                "buyers_60s": len(set(who[burst][w1])),
                "usd_60s_share": float(usd[burst][w1].sum() / max(1.0, bu.sum())),
                "runup": p_now / float(bpx[np.searchsorted(bts, t - 300, side="right")]),
                "off_high": p_now / float(past_held.max()) if nb > 2 else 1.0,
                "fdv": p_now * supply[names[tok]] if names[tok] in supply else np.nan,
                "launch_age_min": (t - first) / 60,
                "depth_usd": depth_at(bpx[:nb], busd[:nb], bts[:nb], t),
                "buyers_hit_rate": hits / n if n >= 3 else np.nan,
                "first3": "", "launcher": "",
            })
    df = pd.DataFrame(rows)
    df.to_parquet(sys.argv[3], index=False)
    print(f"bitti: {len(df)} ikinci dalga anı, {df.coin.nunique()} coin, 2x %{100 * df.t2x_h.notna().mean():.0f} "
          f"({time.time() - t_start:.0f} sn)", flush=True)


if __name__ == "__main__":
    main()
