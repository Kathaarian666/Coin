"""Risky picks under the 5x rule (PROJE.md §0 B4, 9 Oct): the research top 5 % with a security row, split by the flags
known at the alert (no hook on the V4 pool, or an owner other than the shared launchpad owner); for each, the trade's
multiple when it sells at 5x or else after 5 min - 3 h (on-chain value as scripts/exit_truth.py, 0 once pulled), and
for the risky ones that reach 5x the time from the 5x to the liquidity pull.

  python scripts/risky_picks.py <trades.db> <picks.parquet> <exit_truth cache .jsonl> <security.parquet>

picks: the research walk-forward top 5 % (profit_study) or fresh_test.py --picks; the cache: exit_truth.py's events
of those picks; security: security_study.py + security_extra.py (rows at the 3rd buyer, known before the 5th).
"""
import json, sqlite3, sys
import numpy as np, pandas as pd
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from trust_export import flags
BPS = 9.93
p = pd.read_parquet(sys.argv[2]); p['coin'] = p.coin.str.lower()
s = pd.read_parquet(sys.argv[4]); s['token'] = s.token.str.lower(); row = s.drop_duplicates('token').set_index('token')
f = flags(row)
p = p[p.coin.isin(f.index)].copy()
p['risky'] = ((f.hook_yok + f.sahip).reindex(p.coin).values > 0)
ev = {t: [tuple(x) for x in e] for t, e in (json.loads(line) for line in open(sys.argv[3]))}
db = sqlite3.connect(sys.argv[1])
names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}

def value_at(e, fomo_blk, fomo_px, exit_blk):
    """Fomo price at the exit x venue ratio (exit_truth.py logic), 0 if the venue was pulled after its last trade."""
    before = fomo_blk <= exit_blk
    last_fomo = fomo_blk[before][-1]
    p_fomo = float(np.median(fomo_px[before][-5:]))
    upto = [x for x in e if x[0] <= exit_blk]
    trades = [x for x in upto if x[4] == 'trade']
    at = [x for x in trades if x[0] <= last_fomo]
    if not trades:
        return p_fomo
    if not at or not at[-1][3]:
        return np.nan
    venue = at[-1][2]
    last = [x for x in trades if x[2] == venue][-1]
    pulled = any(x[4] == 'pull' and x[2] == venue and x[:2] > last[:2] for x in upto)
    if trades[-1][2] != venue:
        return np.nan
    return 0.0 if pulled else p_fomo * last[3] / at[-1][3]

HOLDS = (5, 10, 15, 20, 30, 60, 180)
rows = []
for r in p.itertuples():
    tr = np.array(db.execute("SELECT ts, block, side, usd, amount FROM trades WHERE token=? ORDER BY ts", (names[r.coin],)).fetchall(), float)
    ts, blk, side = tr[:, 0], tr[:, 1], tr[:, 2]
    px = np.where(tr[:, 4] > 0, tr[:, 3] / np.where(tr[:, 4] > 0, tr[:, 4], 1), np.nan)
    ok = np.isfinite(px)
    pa = px[(side == 1) & (ts <= r.ts) & ok][-1]
    t_in = r.ts + 30
    p_in = px[(side == 1) & (ts <= t_in) & ok][-1]
    ab = blk[ts <= r.ts][-1]
    b = (side == 1) & (ts > t_in) & ok
    hit = np.flatnonzero((px[b][1:] >= 5 * pa) & (px[b][:-1] >= 5 * pa))
    t5 = ts[b][hit[0] + 1] if len(hit) else np.inf
    out = {'risky': r.risky}
    for h in HOLDS:
        if t5 <= r.ts + 60 * h:
            out[h] = 5 * pa / p_in
        else:
            v = value_at(ev.get(r.coin, []), blk[ok], px[ok], ab + int(60 * h * BPS))
            out[h] = v / p_in if v == v else np.nan
    rows.append(out)
x = pd.DataFrame(rows)
print(f"{len(p)} seçim güvenlik bilgisiyle; riskli {int(p.risky.sum())}")
for k, g in x.groupby('risky'):
    print('riskli' if k else 'normal', len(g))
    for h in HOLDS:
        v = g[h]
        print(f'  5x ya da {h:3d} dk: ort {v.mean():.2f}x · medyan {v.median():.2f}x · sıfır {int((v == 0).sum())} · bilinmeyen {int(v.isna().sum())}')

# time from the 5x to the venue's pull, risky picks
gaps = []
for r in p[p.risky].itertuples():
    tr = np.array(db.execute("SELECT ts, block, side, usd, amount FROM trades WHERE token=? ORDER BY ts", (names[r.coin],)).fetchall(), float)
    ts, blk, side = tr[:, 0], tr[:, 1], tr[:, 2]
    px = np.where(tr[:, 4] > 0, tr[:, 3] / np.where(tr[:, 4] > 0, tr[:, 4], 1), np.nan)
    ok = np.isfinite(px)
    pa = px[(side == 1) & (ts <= r.ts) & ok][-1]
    b = (side == 1) & (ts > r.ts + 30) & ok
    hit = np.flatnonzero((px[b][1:] >= 5 * pa) & (px[b][:-1] >= 5 * pa))
    if not len(hit):
        continue
    t5, b5 = ts[b][hit[0] + 1], blk[b][hit[0] + 1]
    pulls = [x[0] for x in ev.get(r.coin, []) if x[4] == 'pull' and x[0] >= b5]
    gaps.append((pulls[0] - b5) / BPS / 60 if pulls else np.inf)
g = pd.Series(gaps)
print('\nriskli, 5x yapan', len(g), '· 5x anından likidite çekilmesine dakika:', sorted(round(v, 1) for v in g if np.isfinite(v)),
      '· çekilmeyen', int(np.isinf(g).sum()))
print('çekilme 1 dk içinde', int((g < 1).sum()), '· 2 dk', int((g < 2).sum()), '· 5 dk', int((g < 5).sum()))
