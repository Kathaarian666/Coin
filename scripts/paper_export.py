"""Train the paper-test model and export it, with the first buyers' record, for the bot (rhscanner/paper.py).

  python scripts/paper_export.py <trades.db> <winners.parquet>

Model: the 2x classifier at the 5th distinct Fomo buyer with the 20 chosen criteria (PROJE.md §4.4: C + D),
trained on every moment with at least 24 h of data; the starting top-2 % bar = 98th percentile of its scores over
the last 2 days of that data (the bot then uses its own live scores). The JSON model is checked against
scikit-learn, and the bot's live feature code (paper.alert_features) against the research table on real coins.
Writes rhscanner/paper_model.json and rhscanner/paper_book.json (wallet -> [coins, 2x within 1 h]).
"""

import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import rise_study  # noqa: E402
from rhscanner import paper  # noqa: E402

K = paper.CHECKPOINT_BUYERS


def export(gbm, features) -> dict:
    trees = []
    for predictor in gbm._predictors:
        nodes = predictor[0].nodes
        trees.append([[int(n["feature_idx"]), float(n["num_threshold"]), bool(n["missing_go_to_left"]),
                       int(n["left"]), int(n["right"]), bool(n["is_leaf"]), float(n["value"])] for n in nodes])
    return {"features": features, "baseline": float(np.ravel(gbm._baseline_prediction)[0]), "trees": trees}


def parity(db, df, launches, supply, n=300):
    """paper.alert_features on the raw trades must give the research table's values."""
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    traders = dict(db.execute("SELECT id, addr FROM names WHERE kind = 'trader'"))
    worst = {}
    for r in df.sample(min(n, len(df)), random_state=1).itertuples():
        rows = db.execute("SELECT ts, block, side, trader, usd, amount FROM trades WHERE token = ? ORDER BY ts",
                          (names[r.coin],)).fetchall()
        trades = [paper.Trade(ts, b, s, traders[tr], u or 0.0, a) for ts, b, s, tr, u, a in rows]
        buyers, i = [], None
        for j, x in enumerate(trades):
            if x.side == 1 and x.trader not in buyers:
                buyers.append(x.trader)
                if len(buyers) == K:
                    i = j
                    break
        f = paper.alert_features(trades, i, K, supply.get(r.coin), launches.get(r.coin), r.buyers_hit_rate)
        for c, v in f.items():
            want = getattr(r, c)
            if (v is None or (isinstance(v, float) and math.isnan(v))) and pd.isna(want):
                continue
            rel = abs(v - want) / max(1e-9, abs(want))
            worst[c] = max(worst.get(c, 0.0), rel)
    return worst


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)
    w = pd.read_parquet(sys.argv[2])
    df = rise_study.load(sys.argv[2], None, K).sort_values("ts").reset_index(drop=True)
    cols = [c for c in rise_study.CHOSEN if c in df]
    live = set(paper.alert_features([paper.Trade(0, 0, 1, "a", 1, 1), paper.Trade(1, 1, 1, "b", 1, 1)], 1, K,
                                    None, None, math.nan))
    missing = [c for c in cols if c not in live]
    if missing:
        raise SystemExit(f"bot bu kriterleri hesaplamıyor: {missing}")
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    y = df.t2x_h.notna()
    gbm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
                                         random_state=0).fit(df[cols], y)
    recent = df[df.ts >= df.ts.max() - 2 * 86400]
    s_recent = gbm.predict_proba(recent[cols])[:, 1]
    data = export(gbm, cols)
    data.update({"bar": float(np.percentile(s_recent, 100 * (1 - paper.TOP))), "trained_until": float(df.ts.max()),
                 "rows": int(len(df)), "positives": int(y.sum()), "k": K})
    model = paper.Model(data)
    sample = df.sample(min(2000, len(df)), random_state=0)
    ours = np.array([model.score({c: row[c] for c in cols}) for _, row in sample.iterrows()])
    diff = float(np.abs(ours - gbm.predict_proba(sample[cols])[:, 1]).max())
    print(f"{len(df)} an (2x: {data['positives']}), {len(cols)} kriter, {len(data['trees'])} ağaç · başlangıç eşiği "
          f"(en iyi %{100 * paper.TOP:g}) {data['bar']:.4f} · sklearn ile en büyük fark {diff:.2e}")
    if diff > 1e-6:
        raise SystemExit("JSON model sklearn ile aynı sonucu vermiyor")

    # the bot's own feature code against the research table
    launch_ts = dict(db.execute("SELECT lower(token), ts FROM launches"))
    supply = {a.lower(): r for a, r in db.execute("SELECT addr, raw FROM supply") if r}
    worst = parity(db, df, launch_ts, supply)
    bad = {c: v for c, v in worst.items() if v > 1e-6}
    print("canlı kriter hesabı ↔ araştırma (en büyük göreli fark):",
          ", ".join(f"{c} {v:.1e}" for c, v in sorted(worst.items(), key=lambda x: -x[1])[:6]))
    if bad:
        raise SystemExit(f"canlı kriter hesabı araştırmadan farklı: {bad}")

    # the first buyers' record as of the data's end (outcome: 2x within 1 h of the 5th-buyer moment)
    traders = dict(db.execute("SELECT id, addr FROM names WHERE kind = 'trader'"))
    k5 = w[(w.k == K) & (w.ts <= data_end - 3600)]
    book: dict[str, list[int]] = {}
    for f, h in zip(k5.first3.fillna(""), (k5.t2x_h.fillna(99) <= 1)):
        for x in f.split(","):
            if x:
                a = traders[int(x)].lower()
                n, k = book.get(a, [0, 0])
                book[a] = [n + 1, k + int(h)]
    (ROOT / "rhscanner" / "paper_model.json").write_text(json.dumps(data, separators=(",", ":")))
    (ROOT / "rhscanner" / "paper_book.json").write_text(json.dumps(book, separators=(",", ":")))
    print(f"yazıldı: paper_model.json, paper_book.json ({len(book)} cüzdan)")


if __name__ == "__main__":
    main()
