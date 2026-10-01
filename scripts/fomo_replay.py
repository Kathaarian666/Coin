"""Backtest the early-entry rule on every Fomo trade of the past days (from scripts/fomo_download.py).

  python scripts/fomo_replay.py <trades.db>

For each coin, every buy is a moment the live bot would check the rule: order-flow features are worked out
from the coin's trades up to then (as momentum.fomo_features). The first moment a setting matches is the
signal; the trade is then replayed on the coin's real Fomo prices: buy at the first buy at least `delay`
seconds later, sell at the target if someone actually sold at or above it within the hour, else sell at the
first sale after the hour. $100 a trade with Fomo's fee (strategy.trade_pnl).

Not reproducible from Fomo alone: the momentum score (liquidity, Fomo's share of all volume) and the trust
checks. FDV assumes 1B tokens (Pons coins); age = time since the coin's first Fomo trade in the data.
"""

import bisect
import itertools
import sqlite3
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.strategy import trade_pnl  # noqa: E402

SUPPLY_RAW = 1e9 * 1e18
DELAYS = (30, 60, 120)
TARGETS = (2.0, 3.0)
HOLD_SEC = 3600
POSITION, FEE_PCT, FEE_MIN = 100.0, 0.5, 0.95
MAX_EVENTS = 300  # per coin


def features(ts, side, trader, usd, i):
    """Order-flow features at trade i (inclusive), like momentum.fomo_features."""
    t = ts[i]
    lo30 = bisect.bisect_right(ts, t - 1800)
    b5, prev, b10, sellers30, buyers30 = set(), set(), set(), set(), set()
    usd10 = 0.0
    for j in range(lo30, i + 1):
        age = t - ts[j]
        if side[j]:
            buyers30.add(trader[j])
            if age < 600:
                b10.add(trader[j])
                usd10 += usd[j] or 0
                (b5 if age < 300 else prev).add(trader[j])
        else:
            sellers30.add(trader[j])
    hold = 1 - len(buyers30 & sellers30) / len(buyers30) if buyers30 else None
    return len(b5), len(prev), len(b10), usd10, hold


def outcome(ts, side, price, t_signal, delay, targets):
    """Multiples for a buy `delay` s after the signal; None if no buy came within 10 minutes.

    Prices are real Fomo fills (USDG per token). A target counts when two buys in a row paid at least that
    within the hour; else the sale is at the median price of the trades in the 10 minutes around the hour. With no trade at all in the 20 minutes before the hour
    the coin is taken as dying: half its last price."""
    j = bisect.bisect_left(ts, t_signal + delay)
    while j < len(ts) and not (side[j] and price[j]) and ts[j] <= t_signal + delay + 600:
        j += 1
    if j >= len(ts) or ts[j] > t_signal + delay + 600 or not price[j]:
        return None
    t_in, p_in = ts[j], price[j]
    end = bisect.bisect_right(ts, t_in + HOLD_SEC)
    path = [(ts[k], side[k], price[k] / p_in) for k in range(j + 1, end) if price[k]]
    lo, hi = bisect.bisect_left(ts, t_in + HOLD_SEC - 600), bisect.bisect_right(ts, t_in + HOLD_SEC + 600)
    around = [price[k] / p_in for k in range(lo, hi) if price[k]]
    recent = [x for t, _, x in path if t >= t_in + HOLD_SEC - 1200]
    dead = not around and not recent
    if around:
        after = statistics.median(around)
    elif recent:
        after = recent[-1]
    else:
        after = (path[-1][2] if path else 1.0) * 0.5
    xs = [x for _, _, x in path]
    # buys only: a sell's dollar size comes from the USDG in its transaction, and Fomo batches several users'
    # trades in one transaction now and then (5% of sells print over 2x the buy before them)
    buys = [x for _, sd, x in path if sd]
    held = [min(a, b) for a, b in zip(buys, buys[1:])]
    out = {"dead": dead, "at60": after, "peak": max(held, default=1.0)}
    for target in targets:
        out[target] = target if any(h >= target for h in held) else after
    return out


def load(db_path):
    db = sqlite3.connect(db_path)
    events, outcomes = [], {}
    tokens = [t for (t,) in db.execute("SELECT DISTINCT token FROM trades")]
    first_all = db.execute("SELECT MIN(ts) FROM trades").fetchone()[0]
    for n, token in enumerate(tokens):
        rows = db.execute("SELECT ts, side, trader, usd, amount FROM trades WHERE token = ? ORDER BY ts, block",
                          (token,)).fetchall()
        if len(rows) < 5:
            continue
        ts = [r[0] for r in rows]
        side = [r[1] for r in rows]
        trader = [r[2] for r in rows]
        usd = [r[3] for r in rows]
        price = [(r[3] / r[4]) if r[3] and r[4] else None for r in rows]
        born = ts[0] if ts[0] > first_all + 3600 else None  # first Fomo trade (unknown if before the data)
        found = 0
        for i in range(len(rows)):
            if not side[i] or found >= MAX_EVENTS:
                continue
            b5, prev, b10, usd10, hold = features(ts, side, trader, usd, i)
            if b5 < 3 or prev > 2 or hold is None or hold < 0.8 or (b10 >= 10 and usd10 >= 500):
                continue
            p = next((price[k] for k in range(i, -1, -1) if price[k]), None)
            if not p:
                continue
            res = {d: outcome(ts, side, price, ts[i], d, TARGETS) for d in DELAYS}
            if res[DELAYS[0]] is None:
                continue
            outcomes[len(events)] = res
            events.append((token, ts[i], b5, prev, b10, usd10 / b10 if b10 else 0, hold, p * SUPPLY_RAW,
                           (ts[i] - born) / 60 if born else 1e9))
            found += 1
        if n % 2000 == 0:
            print(f"{n}/{len(tokens)} coin · {len(events)} olay", flush=True)
    return events, outcomes


def main():
    events, outcomes = load(sys.argv[1])
    ev = np.array([e[1:] for e in events], dtype=float)
    tok = np.array([e[0] for e in events])
    t, b5, prev, b10, avg, hold, fdv, age = ev.T
    cut = np.median(t)
    print(f"\n{len(events)} aday an, {len(set(tok))} coin; dönem ortası {cut:.0f}\n")

    def pnl(idx, delay, target):
        vals = []
        for i in idx:
            o = outcomes[i][delay]
            if o is not None:
                vals.append(trade_pnl([(1.0, o[target])], POSITION, FEE_PCT, FEE_MIN))
        return vals

    grid = {"b5": (3, 4, 5, 6, 8), "prev": (0, 1, 2), "avg": (0, 50, 100, 200), "hold": (0.8, 0.9, 1.0),
            "fdv": (1e12, 100_000, 50_000, 20_000), "age": (1e10, 1440, 360, 60)}
    rows = []
    for combo in itertools.product(*grid.values()):
        B5, P, A, H, F, G = combo
        mask = (b5 >= B5) & (prev <= P) & (avg >= A) & (hold >= H) & (fdv <= F) & (age <= G)
        idx = np.nonzero(mask)[0]
        if len(idx) < 40:
            continue
        _, first = np.unique(tok[idx], return_index=True)  # the first moment per coin (events are in coin order)
        idx = idx[first]
        old, new = idx[t[idx] < cut], idx[t[idx] >= cut]
        if len(old) < 20 or len(new) < 20:
            continue
        po, pn = pnl(old, 60, 3.0), pnl(new, 60, 3.0)
        rows.append({"combo": combo, "n": len(idx), "old": statistics.mean(po), "new": statistics.mean(pn),
                     "n_old": len(po), "n_new": len(pn), "idx": idx})
    print(f"{len(rows)} kombinasyon (her yarıda ≥20 sinyal)\n")

    def show(r):
        B5, P, A, H, F, G = r["combo"]
        idx = r["idx"]
        name = (f"5dk≥{B5} önceki≤{P} alıcıbaşı≥${A} tutma≥{H} FDV≤{'-' if F > 1e11 else f'${F/1000:.0f}k'} "
                f"yaş≤{'-' if G > 1e9 else f'{G:.0f}dk'}")
        extra = []
        for d in DELAYS:
            for target in TARGETS:
                v = pnl(idx, d, target)
                extra.append(f"{d}sn/{target:g}x {statistics.mean(v):+.1f}$")
        wins = pnl(idx, 60, 3.0)
        win = 100 * sum(1 for v in wins if v > 0) / len(wins)
        peak = [outcomes[i][60]["peak"] for i in idx if outcomes[i][60]]
        dead = 100 * sum(1 for i in idx if outcomes[i][60] and outcomes[i][60]["dead"]) / len(idx)
        print(f"{name}\n   {r['n']} sinyal ({r['n'] / 14:.1f}/gün) · kârlı %{win:.0f} · eski {r['old']:+.1f}$ "
              f"({r['n_old']}) · YENİ {r['new']:+.1f}$ ({r['n_new']}) · 1s içinde 2x %"
              f"{100 * sum(1 for p in peak if p >= 2) / len(peak):.0f} · 3x %{100 * sum(1 for p in peak if p >= 3) / len(peak):.0f}"
              f" · ölü %{dead:.0f}\n   " + " · ".join(extra))

    print("== Eski yarıya göre en iyi 10 ==")
    for r in sorted(rows, key=lambda r: -r["old"])[:10]:
        show(r)
    print("\n== İki yarıda da tutarlı en iyi 10 ==")
    for r in sorted(rows, key=lambda r: -min(r["old"], r["new"]))[:10]:
        show(r)
    print("\n== Referans: canlı kuralın Fomo kısmı (5/0/$50/0.8, momentum yok) ==")
    for r in rows:
        if r["combo"] == (5, 0, 50, 0.8, 1e12, 1e10):
            show(r)


if __name__ == "__main__":
    main()
