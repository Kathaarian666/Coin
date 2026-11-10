"""A model trained on one chain's Fomo coins, picking on another's (PROJE.md §4.17, user 10 Nov: BNB is tested, not
dropped). BNB has too few days to train its own model; Robinhood has two months.

  python scripts/cross_chain_test.py <train winners.parquet> <test winners.parquet> <out picks.parquet>
                                     [<first test day>=2026-10-05] [k=5]

Walk-forward as scripts/profit_study.py ("2x" model, same parameters): for each test day the model is trained on the
train chain's moments up to 6 h before the day (2x label only if it was reached before the day began); the test
chain's moments of that day get pct = rank among the test chain's own scores of the 2 days before (as the bot sets
its bar). FDV is left out (no supply data on BNB). Score the picks with scripts/scorecard.py.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rise_study  # noqa: E402

DAY = 86400


def main():
    k = int(sys.argv[5]) if len(sys.argv) > 5 else 5
    cut = pd.Timestamp(sys.argv[4] if len(sys.argv) > 4 else "2026-10-05").value / 1e9
    tr_all = rise_study.load(sys.argv[1], None, k).sort_values("ts")
    te_all = rise_study.load(sys.argv[2], None, k).sort_values("ts")
    cols = [c for c in rise_study.CHOSEN if c in tr_all and c in te_all and c != "fdv"]
    print(f"eğitim {len(tr_all)} an, test {len(te_all)} an, {len(cols)} kriter", flush=True)
    params = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, random_state=0)
    out = []
    for d in sorted(te_all.day.unique()):
        if d < cut // DAY:
            continue
        start = d * DAY
        tr = tr_all[tr_all.ts < start - 6 * 3600]
        y = tr.t2x_h.notna() & (tr.ts + 3600 * tr.t2x_h.fillna(0) < start)
        f = HistGradientBoostingClassifier(**params).fit(tr[cols], y)
        te = te_all[te_all.day == d]
        ref = te_all[(te_all.day >= d - 2) & (te_all.day < d)]
        if not len(te) or not len(ref):
            continue
        r = np.sort(f.predict_proba(ref[cols])[:, 1])
        p = f.predict_proba(te[cols])[:, 1]
        out.append(te.assign(pct=np.searchsorted(r, p) / len(r)))
        print(f"{pd.Timestamp(start, unit='s'):%d %b}: {len(te)} an, en iyi %5: {(out[-1].pct >= 0.95).sum()}", flush=True)
    res = pd.concat(out)
    res.to_parquet(sys.argv[3])
    sel = res[res.pct >= 0.95]
    print(f"bitti: {len(sel)} seçim (en iyi %5), 2x %{100 * sel.hit2x.mean():.0f} (hepsi %{100 * res.hit2x.mean():.0f})")


if __name__ == "__main__":
    main()
