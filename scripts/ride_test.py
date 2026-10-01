"""Buy every coin at its k-th distinct Fomo buyer (+30 s, pool price, fees and slippage) and let winners run.

  python scripts/ride_test.py <trades.db> <k> <cap multiple>

Exits: trailing stop from the running high (two buys in a row), half at 2x + trailing rest, hold 72 h, 2x or 72 h.
One coin's multiple is capped (bad price prints reach millions); "en iyi %1 hariç" drops the best 1%.
"""
import sqlite3, sys, numpy as np, pandas as pd
sys.path.insert(0, 'scripts')
from rise_build import depth_prefix, depth_at, value_after
db = sqlite3.connect(sys.argv[1])
t = pd.read_sql("select ts,token,side,trader,usd,amount from trades where ts>=strftime('%s','2026-09-18') and ts<strftime('%s','2026-10-01 12:00')", db)
end_data = t.ts.max()
b = t[(t.side == 1) & (t.usd > 0) & (t.amount > 0)].sort_values(['token', 'ts']).copy(); b['px'] = b.usd / b.amount
BUYERS = int(sys.argv[2]) if len(sys.argv) > 2 else 10
TRAILS = (0.3, 0.5)
CAP = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
rows = []
for tok, g in b.groupby('token', sort=False):
    ts, px, usd, who = g.ts.values, g.px.values, g.usd.values, g.trader.values
    if ts[0] >= pd.Timestamp('2026-09-28').value / 1e9:  # 72 h must fit in the data
        continue
    s = set(); i = None
    for k, w in enumerate(who):
        s.add(w)
        if len(s) == BUYERS: i = k; break
    if i is None or i + 3 >= len(px) or ts[i] - ts[0] > 6 * 3600:
        continue
    pref = depth_prefix(ts, px, usd)
    depth, _ = depth_at(pref, ts[i])
    t_in = ts[i] + 30
    e = np.searchsorted(ts, t_in, side='right') - 1
    p_in = np.median(px[max(0, e - 2):e + 1]) * (1 + 1.5 * usd[e] / depth)
    end = t_in + 72 * 3600
    path = px[e + 1:np.searchsorted(ts, end, side='right')]
    held = np.minimum(np.minimum(path[:-1], path[1:]) / p_in, CAP) if len(path) > 1 else np.array([])
    res = {'peak': held.max() if len(held) else 0, 'day': int(ts[i] // 86400)}
    final = (np.median(path[-5:]) / p_in) if len(path) else 1.0
    if len(path) and ts[np.searchsorted(ts, end, side='right') - 1] < end - 6 * 3600:
        final *= 0.5  # dead before the end
    final = min(final, held.max()) if len(held) else final
    for x in TRAILS:
        run = np.maximum.accumulate(held) if len(held) else held
        hit = np.nonzero(held <= (1 - x) * run)[0]
        hit = [h for h in hit if run[h] >= 1.0] or [h for h in hit]  # trail from entry too
        out = held[hit[0]] * 0.95 if len(hit) else final
        res[f'trail{x:g}'] = value_after(out, depth)
        # half at 2x (net ~2.1x price), rest trailing
        k2 = np.nonzero(held >= 2.15)[0]
        if len(k2):
            rest = held[k2[0]:]; run2 = np.maximum.accumulate(rest); h2 = np.nonzero(rest <= (1 - x) * run2)[0]
            out2 = rest[h2[0]] * 0.95 if len(h2) else final
            res[f'half2x+trail{x:g}'] = 0.5 * value_after(2.15, depth) + 0.5 * value_after(out2, depth)
        else:
            res[f'half2x+trail{x:g}'] = res[f'trail{x:g}']
    res['hold72'] = value_after(final, depth)
    k2 = np.nonzero(held >= 2.15)[0]
    res['2x/72'] = value_after(2.15, depth) if len(k2) else res['hold72']
    rows.append(res)
d = pd.DataFrame(rows)
print(f"tavan {CAP:g}x · {BUYERS}. alıcıda giriş (+30 sn, kayma+komisyon), {len(d)} coin ({len(d) / d.day.nunique():.0f}/gün), 18-27 Eyl")
print(f"  girişten sonra zirve ≥2x %{100 * (d.peak >= 2).mean():.0f} · ≥5x %{100 * (d.peak >= 5).mean():.0f} · ≥10x %{100 * (d.peak >= 10).mean():.0f}")
for c in [c for c in d.columns if c not in ('peak', 'day')]:
    v = d[c].values; days = d.groupby('day')[c].mean()
    trimmed = np.sort(v)[:int(len(v) * 0.99)].mean()
    print(f"  {c:16} ort {v.mean():+7.1f}$ · en iyi %1 hariç {trimmed:+6.1f}$ · medyan {np.median(v):+6.1f}$ · artı gün {(days > 0).sum()}/{len(days)}")
