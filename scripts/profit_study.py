"""Profit-trained selection (PROJE.md step 3, angle A): teach the model what a trade earns, not whether a 2x comes.

  python scripts/profit_study.py <trades.db> <winners.parquet> [<first test day>=2026-09-10] [k=3]

Every new coin at its 3rd Fomo buyer gets the result of the user's trade (scripts/trade_sim.py rules): bought DELAY s
after the alert at the last price then, half sold at the bot's 2x, the rest on the trailing rule ("iz"), -50 %
stop; a fixed STAKE with Fomo's fee and price impact. Labels for training only use what was known when the test day
began: a trade still open then is valued at the last price at that moment (dead coin: half).
Models, each retrained every day on the days before it (walk-forward, bars from its own scores on the 2 days before):
- 2x: the current classifier (two buys at >= 2x the alert price), the baseline
- kâr>0: classifier, the trade ended in profit after costs
- getiri: regressor on the trade's return (clipped to [-1, 5] so a few 100x coins do not drive it)
Per model and bar: alerts per day, 2x share, mean / median net return per trade, the share of profitable trades,
and each test week alone on a $1000 bankroll (sizes 4 / 2 / 1 %, as in trade_sim).
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rise_study  # noqa: E402
import trade_sim  # noqa: E402
from security_extra import depth_at  # noqa: E402

DELAY = 30
STAKE = 20.0
DAY = 86400
BARS = (0.05, 0.02, 0.01)
MODELS = ("2x", "kâr>0", "getiri")


def leg_value(coins, price, depth):
    value = coins * price
    value *= max(0.0, 1 - value / depth)
    return max(0.0, value - max(trade_sim.FEE_MIN, trade_sim.FEE * value))


def outcomes(db, df):
    """Per coin: entry, exit legs (rule iz), depth; the trades kept for marking open positions."""
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    ids = [names[c] for c in df.coin]
    tr = pd.read_sql(f"SELECT token, ts, side, usd, amount FROM trades WHERE token IN ({','.join(map(str, ids))}) "
                     "ORDER BY token, ts", db)
    by = {i: g for i, g in tr.groupby("token")}
    out = {}
    for key, coin, i, t0 in zip(df.key, df.coin, ids, df.ts):
        g = by[i]
        ts, side = g.ts.values, g.side.values
        px = np.where(g.amount.values > 0, g.usd.values / np.maximum(g.amount.values, 1e-30), np.nan)
        b = (side == 1) & np.isfinite(px)
        p_alert = px[b & (ts <= t0)][-1]
        t_in = t0 + DELAY
        p_in = px[b & (ts <= t_in)][-1]
        depth = depth_at(px[b], g.usd.values[b], ts[b], t0)
        ev, kind = trade_sim.path_events(ts, px, side, t_in, p_in, p_alert, data_end)
        out[key] = dict(ts=ts, px=px, t_in=t_in, p_in=p_in, depth=depth, legs=ev["iz"], kind=kind)
    return out


def trade_return(o, depth, cutoff=np.inf):
    """Net return of a STAKE trade; legs after the cutoff valued at the last price before it."""
    fee = max(trade_sim.FEE_MIN, trade_sim.FEE * STAKE)
    coins = (STAKE - fee) / (o["p_in"] * (1 + STAKE / depth))
    total, open_share = 0.0, 0.0
    for when, share, price in o["legs"]:
        if when <= cutoff:
            total += leg_value(coins * share, price, depth)
        else:
            open_share += share
    if open_share:
        i = np.searchsorted(o["ts"], cutoff, side="right") - 1
        last = o["px"][max(0, i - 4):i + 1] if i >= 0 else []
        last = last[np.isfinite(last)] if len(last) else last
        p = float(np.median(last)) if len(last) else o["p_in"]  # median of the last 5: broken sell prices
        if i >= 0 and cutoff - o["ts"][i] > trade_sim.DEAD:
            p /= 2
        total += leg_value(coins * open_share, min(p, trade_sim.CAP * o["p_in"]), depth)
    return total / STAKE - 1


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)
    cut = pd.Timestamp(sys.argv[3] if len(sys.argv) > 3 else "2026-09-10").value / 1e9
    k = int(sys.argv[4]) if len(sys.argv) > 4 else 3  # angle C: a later moment (5th / 10th buyer; 0 = second waves)
    df = rise_study.load(sys.argv[2], None, k).sort_values("ts").reset_index(drop=True)
    df["key"] = df.coin + "@" + df.ts.astype(str)  # a coin can have several moments (second waves)
    cols = [c for c in rise_study.CHOSEN if c in df]
    print(f"{len(df)} coin, {len(cols)} kriter; işlem sonuçları hesaplanıyor...", flush=True)
    outs = outcomes(db, df)
    med_depth = np.nanmedian([o["depth"] for o in outs.values()])
    for o in outs.values():
        o["depth"] = o["depth"] if np.isfinite(o["depth"]) else med_depth
    df["ret"] = [trade_return(outs[c], outs[c]["depth"]) for c in df.key]
    df["hit2x"] = [outs[c]["kind"] == "2x" for c in df.key]
    print(f"bütün coinler: işlem başına net getiri ort {df.ret.mean():+.2f}, medyan {df.ret.median():+.2f}, "
          f"kârlı %{100 * (df.ret > 0).mean():.0f}\n", flush=True)

    picks = {m: [] for m in MODELS}
    past = {m: [] for m in MODELS}
    for d in sorted(df.day.unique()):
        if d < cut // DAY:
            continue
        start = d * DAY
        tr = df[df.ts < start - 6 * 3600]
        te = df[df.day == d]
        if not len(te):
            continue
        y2x = tr.t2x_h.notna() & (tr.ts + 3600 * tr.t2x_h.fillna(0) < start)
        yret = np.array([trade_return(outs[c], outs[c]["depth"], start) for c in tr.key])
        params = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, random_state=0)
        fits = {
            "2x": HistGradientBoostingClassifier(**params).fit(tr[cols], y2x),
            "kâr>0": HistGradientBoostingClassifier(**params).fit(tr[cols], yret > 0),
            "getiri": HistGradientBoostingRegressor(**params).fit(tr[cols], np.clip(yret, -1, 5)),
        }
        for m, f in fits.items():
            p = f.predict_proba(te[cols])[:, 1] if m != "getiri" else f.predict(te[cols])
            ref = np.concatenate(past[m][-2:]) if past[m] else (
                f.predict_proba(tr[tr.day >= d - 2][cols])[:, 1] if m != "getiri" else f.predict(tr[tr.day >= d - 2][cols]))
            picks[m].append(te.assign(pct=np.searchsorted(np.sort(ref), p) / len(ref)))
            past[m].append(p)

    days = None
    for m in MODELS:
        res = pd.concat(picks[m])
        days = res.day.nunique()
        print(f"== Model: {m}  ({days} test günü)")
        for bar in BARS:
            sel = res[res.pct >= 1 - bar].sort_values("ts")
            if len(sel) < 5:
                continue
            alerts = []
            ranks = sel.pct.rank(pct=True).values
            for (c, q) in zip(sel.key, ranks):
                o = outs[c]
                alerts.append(dict(t_in=o["t_in"], p_in=o["p_in"], depth=o["depth"], events={"iz": o["legs"]},
                                   size=0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01))
            first = sel.ts.min()
            weeks = []
            for wk in range(int((sel.ts.max() - first) // (7 * DAY)) + 1):
                al = [a for a, t in zip(alerts, sel.ts) if first + wk * 7 * DAY <= t < first + (wk + 1) * 7 * DAY]
                if len(al) >= 10 and (sel.ts.max() - first - wk * 7 * DAY) >= 3 * DAY:
                    weeks.append(f"{trade_sim.simulate(al, 'iz', 1000, True) / 1000:.2f}x")
            keep = sel.ret < sel.ret.quantile(0.99)  # luck check: without the best 1 % of the trades
            lucky = [a for a, k in zip(alerts, keep) if k]
            luck = trade_sim.simulate(lucky, "iz", 1000, True) / 1000
            print(f"  en iyi %{100 * bar:g}: günde {len(sel) / days:5.1f} · 2x %{100 * sel.hit2x.mean():.0f} · "
                  f"getiri ort {sel.ret.mean():+.2f} medyan {sel.ret.median():+.2f} · kârlı %{100 * (sel.ret > 0).mean():.0f}"
                  f" · hafta hafta ($1000, masraflı): {' / '.join(weeks)} · 22 gün en iyi %1 hariç {luck:.2f}x "
                  f"(hepsi {trade_sim.simulate(alerts, 'iz', 1000, True) / 1000:.2f}x)")
            sel.assign(model=m, bar=bar).to_parquet(f"/tmp/claude-0/data/profit_k{k}_{m.replace('>', '')}_{bar}.parquet")
        print()


if __name__ == "__main__":
    main()
