"""Risk flags of a set of picks (PROJE.md §4.8): the hook of each pick's V4 pool at the alert (latest Initialize up to
the alert block, searched back up to 2M blocks) + its owner from scripts/security_study.py, written as a security-like
parquet for scripts/risky_picks.py and scripts/exit_truth_rules.py (only hook / owner are real; the other columns are
neutral fillers). One pick at a time: security_extra.py's batch calls are refused when the public node is busy.

  python scripts/pick_flags.py <trades.db> <picks.parquet> <security_study.parquet> <out.parquet>
"""
import sqlite3, sys
import numpy as np, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import exit_truth as et
from rhscanner.hooks import TOPIC_V4_INITIALIZE
p = pd.read_parquet(sys.argv[2]); p['coin'] = p.coin.str.lower()
sec = pd.read_parquet(sys.argv[3]); sec['token'] = sec.token.str.lower()
own = sec.drop_duplicates('token').set_index('token').owner
db = sqlite3.connect(sys.argv[1])
names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}
rows = []
for n, r in enumerate(p.itertuples()):
    f = np.array(db.execute("SELECT ts, block FROM trades WHERE token=? ORDER BY ts", (names[r.coin],)).fetchall())
    ab, first = int(f[f[:, 0] <= r.ts][-1, 1]), int(f[0, 1])
    t = "0x" + "0" * 24 + r.coin[2:]
    def scan(a, b):
        out = []
        for topics in ([TOPIC_V4_INITIALIZE, None, t], [TOPIC_V4_INITIALIZE, None, None, t]):
            for e in et.logs(a, b, topics, et.PM):
                out.append((int(e["blockNumber"], 16), "0x" + e["data"][2 + 64 * 2 + 24: 2 + 64 * 3]))
        return out
    found = scan(first, ab)
    for a in range(first - et.CHUNK, max(0, first - 2_000_000) - 1, -et.CHUNK):
        if found:
            break
        found = scan(max(0, a), a + et.CHUNK - 1)
    hook = max(found)[1] if found else ""
    rows.append({"token": r.coin, "owner": own.get(r.coin), "hook": hook, "pons": bool(r.is_pons), "fomo_sellers": 0,
                 "proxy": 0, "risky": "", "dev_pct": 0.0, "depth_usd": np.nan, "hook_named": False,
                 "obs_h": 99, "trap": False, "t0": r.ts})
    if n % 10 == 0:
        print(n, len(p), flush=True)
out = pd.DataFrame(rows)
out.to_parquet(sys.argv[4], index=False)
print('owner bilinen', out.owner.notna().sum(), '/', len(out), '· hook yok', (out.hook == '0x' + '0' * 40).sum(), '· havuz yok', (out.hook == '').sum())
