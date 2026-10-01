"""Research table for "will my money double?": one row per candidate moment, real Fomo prices, no fixed exit.

  python scripts/rise_build.py <out.parquet> <trades.db>

Candidates: each coin's first buy in a minute with at least 3 distinct buyers in the last 5 minutes.
Entry: the first buy 30 s after the moment, at its price plus our own slippage. The pool's dollar depth R is
estimated from the coin's back-to-back buys in the 15 minutes before the moment (price step ~ trade size / R).
Label `hit`: the money doubles after fees and slippage, i.e. two buys in a row at or above the needed price
multiple, within 72 h (`t_hit` minutes; `low` = lowest buy price before that, as a multiple of the entry).
If it never doubles, `final` is the price at the end of the 72 h (dead coins: half the last price) and
`pnl` the $ result of holding $100 that long. `obs_h` = hours actually observed (data gaps / data end): a
label is only complete for horizons up to obs_h.
Features: rhscanner.flow.flow_features plus the coin's history so far and `smart10` (buyers in the last 10
minutes whose earlier first buys in other coins doubled at least twice, known only once they did).
"""

import bisect
import sqlite3
import sys
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.flow import flow_features  # noqa: E402

DELAY = 30
HORIZON = 72 * 3600
FEE = 0.005
POSITION = 100.0
DEFAULT_DEPTH = 5600.0
GAP = 6 * 3600  # a pause this long in all trading = a hole in the data


class Sparse:
    """O(1) range min / max and 'first index from j with value >= x' over a fixed array."""

    def __init__(self, values: np.ndarray, op):
        self.op, self.levels = op, [values]
        k = 1
        while 2 * k <= len(values):
            prev = self.levels[-1]
            self.levels.append(op(prev[:-k], prev[k:]))
            k *= 2

    def query(self, lo: int, hi: int) -> float:  # inclusive
        lvl = (hi - lo + 1).bit_length() - 1
        t = self.levels[lvl]
        return self.op(t[lo], t[hi - (1 << lvl) + 1])

    def first_at_least(self, lo: int, x: float) -> int:
        """First index >= lo whose value >= x (max table only); len if none."""
        n, pos = len(self.levels[0]), lo
        for lvl in range(len(self.levels) - 1, -1, -1):
            if pos + (1 << lvl) <= n and self.levels[lvl][pos] < x:
                pos += 1 << lvl
        return pos


@lru_cache(maxsize=None)
def _needed(depth: float) -> float:
    """Price multiple at which $100 in comes back as $200 after Fomo fees and slippage both ways."""
    s_in = POSITION / depth
    for m in np.arange(1.9, 6.0, 0.01):
        s_out = min(0.5, 2 * POSITION / (depth * np.sqrt(m)))
        if (1 - FEE) ** 2 / (1 + s_in) * m * (1 - s_out) >= 2:
            return float(m)
    return 6.0


def needed_multiple(depth: float) -> float:
    return _needed(float(round(depth, -2)))


def value_after(final: float, depth: float) -> float:
    s_in = POSITION / depth
    s_out = min(0.5, POSITION * final / (depth * np.sqrt(max(final, 0.05))))
    return POSITION * (1 - FEE) ** 2 / (1 + s_in) * final * (1 - s_out) - POSITION


def segments(all_ts: np.ndarray) -> list[tuple[float, float]]:
    ts = np.sort(all_ts)
    cut = np.nonzero(np.diff(ts) > GAP)[0]
    starts = np.r_[ts[0], ts[cut + 1]]
    ends = np.r_[ts[cut], ts[-1]]
    return list(zip(starts, ends))


def load(path):
    db = sqlite3.connect(path)
    supply = {a: raw for a, raw in db.execute("SELECT addr, raw FROM supply") if raw}
    names = {(k, i): a for i, k, a in db.execute("SELECT id, kind, addr FROM names")}
    coins: dict[str, list] = defaultdict(list)
    traders: dict[str, int] = {}
    for ts, tok, side, trd, usd, amount in db.execute("SELECT ts, token, side, trader, usd, amount FROM trades"):
        who = traders.setdefault(names[("trader", trd)], len(traders))
        coins[names[("token", tok)]].append((ts, side, who, usd, (usd / amount) if usd and amount else None))
    for rows in coins.values():
        rows.sort(key=lambda r: r[0])
    return coins, supply


def buy_series(rows):
    b = [(r[0], r[4], r[3], r[2]) for r in rows if r[1] and r[4]]
    ts = np.array([x[0] for x in b], float)
    px = np.array([x[1] for x in b], float)
    usd = np.array([x[2] or 0 for x in b], float)
    who = [x[3] for x in b]
    return ts, px, usd, who


def depth_prefix(ts, px, usd):
    """Cumulative sums for a through-origin fit of (price step) on (size of the two buys), pairs <= 60 s apart."""
    if len(px) < 2:
        return ts[:0], np.zeros(1), np.zeros(1), np.zeros(1)
    x = usd[:-1] + usd[1:]
    y = px[1:] / px[:-1] - 1
    ok = (ts[1:] - ts[:-1] <= 60) & (x > 0) & (np.abs(y) < 1)
    x, y = np.where(ok, x, 0), np.where(ok, y, 0)
    return ts[1:], np.r_[0, np.cumsum(x * y)], np.r_[0, np.cumsum(x * x)], np.r_[0, np.cumsum(ok)]


def depth_at(pref, t):
    """Pool depth from the buys of the last 15 minutes, else of the coin's whole past, else a typical value."""
    pts, sxy, sxx, n = pref
    hi = bisect.bisect_right(pts, t)
    for lo in (bisect.bisect_left(pts, t - 900), 0):
        if n[hi] - n[lo] >= 5 and sxy[hi] - sxy[lo] > 0:
            return float(np.clip((sxx[hi] - sxx[lo]) / (sxy[hi] - sxy[lo]), 1000, 1e6)), True
    return DEFAULT_DEPTH, False


def main():
    out, path = sys.argv[1], sys.argv[2]
    t0 = time.time()
    coins, supply = load(path)
    segs = segments(np.array([r[0] for rows in coins.values() for r in rows[:1]] +
                             [r[0] for rows in coins.values() for r in rows[-1:]] +
                             [r[0] for rows in coins.values() for r in rows[::50]]))
    seg_starts = [s for s, _ in segs]
    print(f"{len(coins)} coin, veri parçaları: " + ", ".join(
        f"{pd.to_datetime(s, unit='s'):%d.%m %H:%M}–{pd.to_datetime(e, unit='s'):%d.%m %H:%M}" for s, e in segs)
        + f" ({time.time() - t0:.0f} sn)", flush=True)

    def seg_end(t):
        return segs[bisect.bisect_right(seg_starts, t) - 1][1]

    def seg_start(t):
        return segs[bisect.bisect_right(seg_starts, t) - 1][0]

    # pass 1: per coin buy series, and each wallet's doubled first buys (known at the time they doubled)
    series, wins = {}, defaultdict(list)
    for coin, rows in coins.items():
        ts, px, usd, who = buy_series(rows)
        if len(px) < 3:
            continue
        held = np.minimum(px[:-1], px[1:])
        series[coin] = (ts, px, usd, who, Sparse(held, np.maximum), Sparse(px, np.minimum))
        seen = set()
        for k, w in enumerate(who):
            if w in seen or k + 1 >= len(held):
                continue
            seen.add(w)
            hit = series[coin][4].first_at_least(k + 1, 2 * px[k])
            if hit < len(held) and ts[hit + 1] - ts[k] <= HORIZON:
                wins[w].append(ts[hit + 1])
    for w in wins:
        wins[w].sort()

    def known_wins(w, t):
        return bisect.bisect_right(wins[w], t) if w in wins else 0

    print(f"cüzdan geçmişi hazır: {len(wins)} cüzdanın en az 1 ikiye katlaması ({time.time() - t0:.0f} sn)", flush=True)

    records = []
    for n, (coin, rows) in enumerate(coins.items()):
        if coin not in series:
            continue
        bts, bpx, busd, _, hmax, pmin = series[coin]
        pref = depth_prefix(bts, bpx, busd)
        ts = [r[0] for r in rows]
        side = [r[1] for r in rows]
        trader = [r[2] for r in rows]
        usd = [r[3] for r in rows]
        price = [r[4] for r in rows]
        first_ts = ts[0]
        if first_ts - seg_start(first_ts) < GAP:
            continue  # first seen right after a data hole: its true age and history are unknown
        first_price = next((p for s, p in zip(side, price) if s and p), None)
        buyers_so_far, sellers_so_far, usd_so_far = set(), set(), 0.0
        minute_done, j_prev = -1, 0
        for i in range(len(rows)):
            for k in range(j_prev, i + 1):
                (buyers_so_far if side[k] else sellers_so_far).add(trader[k])
                if side[k]:
                    usd_so_far += usd[k] or 0
            j_prev = i + 1
            if not side[i] or int(ts[i] // 60) == minute_done:
                continue
            lo = bisect.bisect_right(ts, ts[i] - 300)
            if len({trader[j] for j in range(lo, i + 1) if side[j]}) < 3:
                continue
            minute_done = int(ts[i] // 60)
            t = ts[i]
            j = bisect.bisect_left(bts, t + DELAY)
            if j >= len(bts) - 2 or bts[j] > t + DELAY + 600:
                continue
            t_in, p_in = bts[j], bpx[j]
            depth, depth_known = depth_at(pref, t)
            need = needed_multiple(depth)
            end = min(t_in + HORIZON, seg_end(t_in))
            last = bisect.bisect_right(bts, end) - 1
            hit_k = hmax.first_at_least(j + 1, need * p_in) if j + 1 < len(bts) - 1 else len(bts)
            hit = hit_k < len(bts) - 1 and bts[hit_k + 1] <= end
            if hit:
                low = pmin.query(j, hit_k + 1) / p_in
                t_hit = (bts[hit_k + 1] - t_in) / 60
                final = need
                pnl = POSITION
            else:
                low = pmin.query(j, max(j, last)) / p_in
                t_hit = np.nan
                w = (bts >= end - 3600) & (bts <= end)
                if w.any():
                    final = float(np.median(bpx[w])) / p_in
                else:
                    final = bpx[last] / p_in * (0.5 if end - bts[last] > 6 * 3600 else 1.0)
                pnl = value_after(final, depth)
            f = flow_features(ts, side, trader, usd, price, i, first_ts, first_price, known_wins,
                              supply.get(coin))
            hmax_so_far = hmax.query(0, max(0, bisect.bisect_right(bts, t) - 2)) if bisect.bisect_right(bts, t) >= 2 else p_in
            f.update({
                "coin": coin, "ts": t, "buyers_all": len(buyers_so_far), "sellers_all": len(sellers_so_far),
                "usd_all": usd_so_far, "off_peak": (f["runup"] * first_price / hmax_so_far) if first_price and hmax_so_far else 1.0,
                "depth": depth, "depth_known": depth_known, "need": need, "hit": hit, "t_hit": t_hit, "low": low, "final": final, "pnl": pnl,
                "obs_h": (end - t_in) / 3600,
            })
            records.append(f)
        if n % 3000 == 0:
            print(f"{n}/{len(coins)} coin · {len(records)} an · {time.time() - t0:.0f} sn", flush=True)
    df = pd.DataFrame.from_records(records)
    df["coin"] = df["coin"].astype("category")
    df.to_parquet(out)
    print(f"bitti: {len(df)} an, {df['coin'].nunique()} coin ({time.time() - t0:.0f} sn)", flush=True)


if __name__ == "__main__":
    main()
