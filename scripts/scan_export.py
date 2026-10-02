"""Train the rise scan on all research checkpoints and export it as JSON for the bot (rhscanner/scan.py).

  python scripts/scan_export.py <trades.db> <out.json> <winners.parquet> [<winners.parquet> ...]

Same model as the walk-forward research (scripts/exit_search.py): gradient boosting on the 3rd-Fomo-buyer
checkpoints, label = held 5x within 24 h, features = rhscanner.scan.FEATURES (the ones the bot computes live).
Trained on checkpoints whose 24 h label is complete; the starting top-10% / top-20% bars are percentiles of
its scores over the last 2 days of that data (the bot then uses its own live scores). The JSON model is checked against scikit-learn before writing.
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from exit_search import paths_and_peak24  # noqa: E402
from rhscanner.scan import FEATURES, ScanModel  # noqa: E402


def export(gbm, features) -> dict:
    trees = []
    for predictor in gbm._predictors:
        nodes = predictor[0].nodes
        trees.append([[int(n["feature_idx"]), float(n["num_threshold"]), bool(n["missing_go_to_left"]),
                       int(n["left"]), int(n["right"]), bool(n["is_leaf"]), float(n["value"])] for n in nodes])
    return {"features": features, "baseline": float(np.ravel(gbm._baseline_prediction)[0]), "trees": trees}


def main():
    db = sqlite3.connect(sys.argv[1])
    out = sys.argv[2]
    frames = [pd.read_parquet(p) for p in sys.argv[3:]]
    df = pd.concat([f[f.k == 3][["coin", "ts"] + FEATURES] for f in frames]).sort_values("ts").reset_index(drop=True)
    df[FEATURES] = df[FEATURES].astype(float)
    _, peak24 = paths_and_peak24(db, df)
    df["peak24"] = [peak24[(c, t)] for c, t in zip(df.coin, df.ts)]
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    train = df[df.ts < data_end - 86400]
    gbm = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.04, min_samples_leaf=40, l2_regularization=1.0,
                                         random_state=0).fit(train[FEATURES], train.peak24 >= 5)
    # the starting bars, as in the walk-forward research: percentiles of the model's scores on the last 2 days of
    # its data; the bot moves to its own live scores once it has scored enough coins (ScanLog.bars)
    recent = train[train.ts >= train.ts.max() - 2 * 86400]
    s_recent = gbm.predict_proba(recent[FEATURES])[:, 1]
    data = export(gbm, FEATURES)
    data.update({"bar10": float(np.percentile(s_recent, 90)), "bar20": float(np.percentile(s_recent, 80)),
                 "trained_until": float(train.ts.max()), "rows": int(len(train)),
                 "positives": int((train.peak24 >= 5).sum())})
    model = ScanModel(data)
    sample = df.sample(min(2000, len(df)), random_state=0)
    ours = np.array([model.score({f: row[f] for f in FEATURES}) for _, row in sample.iterrows()])
    theirs = gbm.predict_proba(sample[FEATURES])[:, 1]
    diff = float(np.abs(ours - theirs).max())
    print(f"{len(train)} kontrol noktası (≥5x/24 s: {data['positives']}), {len(data['trees'])} ağaç · bar %10 "
          f"{data['bar10']:.4f} · bar %20 {data['bar20']:.4f} · sklearn ile en büyük fark {diff:.2e}")
    if diff > 1e-6:
        raise SystemExit("JSON model sklearn ile aynı sonucu vermiyor")
    Path(out).write_text(json.dumps(data, separators=(",", ":")))
    print(f"yazıldı: {out} ({Path(out).stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
