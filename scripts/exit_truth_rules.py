"""The exit-rule search again, with the on-chain exit value instead of the last Fomo price (PROJE.md §0 A10, §4.4b).

  python scripts/exit_truth_rules.py <trades.db> <walk-forward picks.parquet> <truth.parquet from exit_truth.py>
                                     [<security.parquet>] [<last exploration day>=2026-09-30]

Same alerts, costs and weekly bankroll as scripts/exit_study.py; only time-limited rules (hold 1 / 3 / 6 / 24 h, the
exits exit_truth.py measured). Targets, stops and trails sell at real Fomo trades (they happened, so they were
sellable); what is still held at the time limit is worth the last Fomo price (median of the last 5) x the measured
on-chain ratio — 0 once the pool's liquidity was pulled. A ratio that could not be measured (the coin changed venue)
is valued two ways: at the Fomo price (high) and at 0 (low). Pick filters against rugs, all known at the alert:
- pons: only coins launched on Pons (the rugs among the top picks were plain V4 pools, PROJE.md §4.4b)
- guven50: trust score >= 50 (rhscanner/trust_model.json flags at the 3rd buyer, PROJE.md §4.1), the logistic
  regression refit every day on the days before it (walk-forward); coins without a security row are kept
Rules are chosen on the days up to <last exploration day>; the later days (final exam) are only reported for the
chosen rules.
"""

import itertools
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trade_sim  # noqa: E402
from exit_study import Path_, weeks  # noqa: E402
from security_extra import depth_at  # noqa: E402
from trust_export import flags  # noqa: E402

TPS = (2.0, 3.0, 5.0)
SHARES = (0.0, 0.5, 1.0)
STOPS = (0.5, None)
TRAILS = (0.5, None)
HOLDS = (1, 3, 6, 24)
PICKS = (0.01, 0.02)


def trust_scores(sec: pd.DataFrame, picks: pd.DataFrame) -> pd.Series:
    """Walk-forward trust score of each pick (NaN without a security row or before 2 days of known labels)."""
    sec = sec[sec.obs_h >= 24].copy()
    sec["token"] = sec.token.str.lower()
    sec["day"] = pd.to_datetime(sec.t0, unit="s").dt.floor("D")
    X, y = flags(sec), sec.trap.astype(int)
    row = sec.drop_duplicates("token").set_index("token")
    Xr = flags(row)
    out = {}
    for day, g in picks.groupby(pd.to_datetime(picks.ts, unit="s").dt.floor("D")):
        train = (sec.t0 + 86400 < day.value / 1e9).values  # its trap label (24 h later) known by then
        if sec.day[train].nunique() < 2 or y[train].nunique() < 2:
            continue
        m = LogisticRegression(max_iter=1000).fit(X[train], y[train])
        known = [c for c in g.coin if c in Xr.index]
        if known:
            p = m.predict_proba(Xr.loc[known])[:, 1]
            out.update(zip(known, np.clip(100 * (1 - p / 0.5), 0, 100)))
    return picks.coin.map(out)


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)
    picks = pd.read_parquet(sys.argv[2])
    picks["coin"] = picks.coin.str.lower()
    truth = pd.read_parquet(sys.argv[3])
    truth["coin"] = truth.coin.str.lower()
    picks = picks[picks.coin.isin(truth.coin)].sort_values("ts").reset_index(drop=True)
    picks["trust"] = trust_scores(pd.read_parquet(sys.argv[4]), picks) if len(sys.argv) > 4 else np.nan
    last = pd.Timestamp(sys.argv[5] if len(sys.argv) > 5 else "2026-09-30").value / 1e9 + 86400
    truth = truth.set_index("coin")
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    rules = [r for r in itertools.product(TPS, SHARES, STOPS, TRAILS, HOLDS) if not (r[1] == 1.0 and r[3] is not None)]
    alerts = []
    for r in picks.itertuples():
        g = pd.read_sql("SELECT ts, side, usd, amount FROM trades WHERE token = ? AND ts <= ? ORDER BY ts", db,
                        params=(names[r.coin], data_end))
        ts, side, usd = g.ts.values, g.side.values, g.usd.values
        px = np.where(g.amount > 0, g.usd / g.amount.where(g.amount > 0), np.nan)
        b = (side == 1) & np.isfinite(px)
        path = Path_(ts, px, side, r.ts, data_end)
        tr = truth.loc[r.coin]
        a = {"t_in": path.t_in, "p_in": path.p_in, "pct": r.pct, "exam": r.ts >= last,
             "pons": bool(r.is_pons), "trust": r.trust, "depth": depth_at(px[b], usd[b], ts[b], r.ts)}
        for rule in rules:
            legs = path.legs(*rule)
            t_end = r.ts + 3600 * rule[4]
            ratio = tr[f"ratio_{rule[4]}"]
            for mode in ("hi", "lo"):
                out = []
                for t, sh, p in legs:
                    if t >= t_end - 1e-6:  # still held at the time limit: the on-chain value
                        i = np.searchsorted(path.ts, t_end, side="right") - 1
                        fomo = float(np.median(path.px[max(0, i - 4):i + 1])) if i >= 0 else path.p_in
                        p = fomo * (ratio if ratio == ratio else (1.0 if mode == "hi" else 0.0))
                    out.append((t, sh, p))
                a[(rule, mode)] = out
        alerts.append(a)
    med = np.nanmedian([a["depth"] for a in alerts])
    for a in alerts:
        a["depth"] = a["depth"] if np.isfinite(a["depth"]) else med
        a["legs"] = {k: v for k, v in a.items() if isinstance(k, tuple)}
    n_unknown = {h: int(truth[f"ratio_{h}"].isna().sum()) for h in HOLDS}
    n_pulled = {h: int(truth[f"pulled_{h}"].fillna(False).astype(bool).sum()) for h in HOLDS}
    print(f"{len(alerts)} seçim ({sum(a['exam'] for a in alerts)} final sınavında); ölçülemeyen oran {n_unknown}, "
          f"likiditesi çekilmiş {n_pulled}\n")
    filters = {"hepsi": lambda a: True, "pons": lambda a: a["pons"],
               "guven50": lambda a: not a["trust"] >= 0 or a["trust"] >= 50}
    rows = []
    for pick, (fname, keep), rule, mode, sizing in itertools.product(
            PICKS, filters.items(), rules, ("hi", "lo"), ("ranked", "flat")):
        sel = [a for a in alerts if a["pct"] >= 1 - pick and not a["exam"] and keep(a)]
        ranks = pd.Series([a["pct"] for a in sel]).rank(pct=True).values
        for a, q in zip(sel, ranks):
            a["ranked"] = 0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01
            a["flat"] = 0.02
        w = weeks(sel, (rule, mode), sizing) if sel else []
        if not w:
            continue
        mult = [sum(sh * p for _, sh, p in a["legs"][(rule, mode)]) / a["p_in"] for a in sel]
        cut = np.quantile(mult, 0.99)
        wl = weeks([a for a, m in zip(sel, mult) if m < cut], (rule, mode), sizing) or [np.nan]
        rows.append({"pick": pick, "filter": fname, "tp": rule[0], "share": round(rule[1], 2), "stop": rule[2],
                     "trail": rule[3], "hold": rule[4], "mode": mode, "size": sizing, "n": len(sel),
                     "weeks": " / ".join(f"{x:.2f}" for x in w), "geo": float(np.prod(w) ** (1 / len(w))),
                     "worst": min(w), "geo_luck": float(np.prod(wl) ** (1 / len(wl)))})
    df = pd.DataFrame(rows)
    df.to_parquet(Path(sys.argv[3]).with_name("exit_truth_rules.parquet"), index=False)
    cols = ["pick", "filter", "tp", "share", "stop", "trail", "hold", "size", "n", "weeks", "geo", "worst", "geo_luck"]
    key = ["pick", "filter", "tp", "share", "stop", "trail", "hold", "size"]
    both = df[df["mode"] == "lo"].merge(df[df["mode"] == "hi"][key + ["geo"]], on=key, suffixes=("", "_hi"))
    base = both[(both.pick == 0.02) & (both.tp == 2.0) & (both.share == 0.5) & (both.stop == 0.5)
                & (both.trail == 0.5) & (both["size"] == "ranked")]
    print("Şimdiki kurallara en yakın (en iyi %2, 2x'te yarı, %50 zarar-kes, zirveden %50; süre sınırı ile) — "
          "geo = ölçülemeyen 0, geo_hi = ölçülemeyen Fomo fiyatı:")
    print(base[cols + ["geo_hi"]].to_string(index=False))
    for fname in filters:
        print(f"\nEn iyi 8 — filtre {fname} (ölçülemeyen 0 sayılarak, haftalık geometrik ortalama):")
        print(both[both["filter"] == fname].sort_values("geo", ascending=False).head(8)[cols + ["geo_hi"]]
              .to_string(index=False))
    print("\nOlağan değerlemeyle (exit_study) en iyi kural, gerçek değerle: en iyi %2, 5x'te yarı, %50/%50, 1 sa, 4/2/1:")
    print(both[(both.pick == 0.02) & (both.tp == 5.0) & (both.share == 0.5) & (both.stop == 0.5) & (both.trail == 0.5)
               & (both.hold == 1) & (both["size"] == "ranked")][cols + ["geo_hi"]].to_string(index=False))
    exam = [a for a in alerts if a["exam"]]
    if exam:
        print(f"\nFinal sınavı (1 Ekim+): {len(exam)} seçim — hafta oluşmaz; işlem başı çarpanlar (en iyi kural, lo):")
        best = both.sort_values("geo", ascending=False).iloc[0]
        rule = (best.tp, best.share, best.stop if best.stop == best.stop else None,
                best.trail if best.trail == best.trail else None, int(best.hold))
        for a in exam:
            legs = a["legs"].get((rule, "lo"))
            if legs:
                print(f"  {sum(sh * p for _, sh, p in legs) / a['p_in']:.2f}x")
    print(f"\nyazıldı: {Path(sys.argv[3]).with_name('exit_truth_rules.parquet')}")


if __name__ == "__main__":
    main()
