"""Is the best true-value rule (sell everything at 5x, 3 h limit; scripts/exit_truth_rules.py) still good when the
user sells late? (PROJE.md §4.4c, A10)

  python scripts/exit_truth_delay.py   (paths: /tmp/claude-0/data/, the research session's layout)

The target is seen on Fomo (two buys in a row at >= 5x); the sale happens 0 / 60 / 300 / 900 s later at the on-chain
price then (exit_truth.py events: the venue's price ratio, 0 once its liquidity was pulled). Also checks that the
Fomo 5x is a 5x on-chain (venue price at the hit / at the alert).
"""
import json, sqlite3, sys
import numpy as np, pandas as pd
sys.path.insert(0, '/home/user/Coin/scripts')
from exit_study import Path_, weeks
from security_extra import depth_at
D = '/tmp/claude-0/data/'
db = sqlite3.connect(D + 'fomo.db')
ev = {t: [tuple(e) for e in e_] for t, e_ in (json.loads(l) for l in open(D + 'truth_top2.cache.jsonl'))}
truth = pd.read_parquet(D + 'truth_top2.parquet')
picks = pd.read_parquet(D + 'profit_k5_2x_0.05.parquet'); picks = picks[picks.pct >= 0.98].sort_values('ts')
picks = picks[picks.ts < pd.Timestamp('2026-10-01').value / 1e9]
names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}
data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
RULE = (5.0, 1.0, None, None, 3)
DELAYS = (0, 60, 300, 900)
alerts, stats = [], []
for r in picks.itertuples():
    g = pd.read_sql("SELECT ts, block, side, usd, amount FROM trades WHERE token=? AND ts<=? ORDER BY ts", db, params=(names[r.coin], data_end))
    ts, side, usd, blk = g.ts.values, g.side.values, g.usd.values, g.block.values
    px = np.where(g.amount > 0, g.usd / g.amount.where(g.amount > 0), np.nan)
    b = (side == 1) & np.isfinite(px)
    path = Path_(ts, px, side, r.ts, data_end)
    legs = path.legs(*RULE)
    a = {"t_in": path.t_in, "p_in": path.p_in, "pct": r.pct, "depth": depth_at(px[b], usd[b], ts[b], r.ts), "legs": {}}
    t_hit = legs[0][0]
    hit = legs[0][0] < r.ts + 3 * 3600 - 1 and abs(legs[0][2] - 5 * path.p_alert) < 1e-12 * max(1, legs[0][2])
    tr = truth.set_index('coin').loc[r.coin]
    for d in DELAYS:
        if not hit:  # time exit: as exit_truth_rules (lo)
            ratio = tr['ratio_3']
            i = np.searchsorted(path.ts, r.ts + 3 * 3600, side='right') - 1
            fomo = float(np.median(path.px[max(0, i - 4):i + 1])) if i >= 0 else path.p_in
            a["legs"][d] = [(legs[0][0], 1.0, fomo * (ratio if ratio == ratio else 0.0))]
            continue
        hb = int(blk[np.searchsorted(ts, t_hit, side='right') - 1])
        tb = hb + int(d * 9.93)
        e = ev[r.coin]
        trades = [x for x in e if x[4] == 'trade']
        at = [x for x in trades if x[0] <= hb]
        val = np.nan
        if at:
            V = at[-1][2]
            last = [x for x in trades if x[2] == V and x[0] <= tb][-1]
            pulled = any(x[4] == 'pull' and x[2] == V and at[-1][:2] < x[:2] and x[0] <= tb and x[:2] > last[:2] for x in e)
            val = 0.0 if pulled else last[3] / at[-1][3]
        stats.append((d, val))
        a["legs"][d] = [(t_hit + d, 1.0, 5 * path.p_alert * (val if val == val else 1.0))]
    alerts.append(a)
med = np.nanmedian([a["depth"] for a in alerts])
ranks = pd.Series([a["pct"] for a in alerts]).rank(pct=True).values
for a, q in zip(alerts, ranks):
    a["depth"] = a["depth"] if np.isfinite(a["depth"]) else med
    a["ranked"] = 0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01
s = pd.DataFrame(stats, columns=['d', 'val'])
print('5x hedefine ulaşan seçim:', (s.d == 0).sum(), 'of', len(alerts))
for d in DELAYS:
    v = s[s.d == d].val
    w = weeks(alerts, d, 'ranked')
    print(f"gecikme {d:4d} sn: hedef anı fiyatına oran medyan {v.median():.2f}, çeyrek {v.quantile(.25):.2f}, sıfır (çekilmiş) {int((v == 0).sum())}, "
          f"bilinmeyen {int(v.isna().sum())} | haftalar {' / '.join(f'{x:.2f}' for x in w)}, geo {np.prod(w) ** (1 / len(w)):.2f}")

# on-chain check: venue price at the hit block / venue price at the alert block
chk = []
for r in picks.itertuples():
    g = pd.read_sql("SELECT ts, block, side, usd, amount FROM trades WHERE token=? AND ts<=? ORDER BY ts", db, params=(names[r.coin], data_end))
    ts, side, blk = g.ts.values, g.side.values, g.block.values
    px = np.where(g.amount > 0, g.usd / g.amount.where(g.amount > 0), np.nan)
    path = Path_(ts, px, side, r.ts, data_end)
    legs = path.legs(*RULE)
    if not (legs[0][0] < r.ts + 3 * 3600 - 1 and abs(legs[0][2] - 5 * path.p_alert) < 1e-12 * max(1, legs[0][2])):
        continue
    ab = int(blk[ts <= r.ts][-1]); hb = int(blk[np.searchsorted(ts, legs[0][0], side='right') - 1])
    trades = [x for x in ev[r.coin] if x[4] == 'trade']
    a0 = [x for x in trades if x[0] <= ab]; h0 = [x for x in trades if x[0] <= hb]
    same = a0 and h0 and a0[-1][2] == h0[-1][2]
    chk.append({"coin": r.coin, "pons": r.is_pons, "fomo_x": legs[0][2] / path.p_alert,
                "chain_x": h0[-1][3] / a0[-1][3] if same else np.nan, "venue_moved": not same,
                "min": (legs[0][0] - r.ts) / 60})
c = pd.DataFrame(chk)
print(c.describe().to_string()); print('venue moved', c.venue_moved.sum(), 'chain_x<3:', (c.chain_x < 3).sum(), 'pons share', c.pons.mean())
print(c.sort_values('chain_x').head(8).to_string())
