"""pump.fun: a model trained on the trade's result instead of on 2x (PROJE.md §0 A8, user 9 Oct "7 a").

  python scripts/pump_profit.py <solana.db> <pump_study.parquet> [<top share>=0.02]

Every 5th-buyer moment (coins over 90 % of the curve left out, 3 h of data after it) gets the result of each sell rule
as scripts/pump_sim.py trades it (30 s late, pump.fun fee, exit at the curve's spot): the multiple of the entry money,
before Fomo's fee. Per rule, each test day is scored by a regression model (the bot's tree settings) trained on the
days before it on that multiple (capped at 5x), the day's top share is picked and simulated with Fomo's fee and price
impact (trade_sim). Beside it, the 2x model's picks (scripts/pump_rise.py) under the same rule.
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trade_sim  # noqa: E402
from pump_rise import FEATURES, PARAMS, prepare, walk_forward  # noqa: E402
from pump_sim import HOLD_MIN, load, make_alert  # noqa: E402

RULES = {
    "5x'te hepsi, 3 sa": (5.0, 1.0, None, None, 3),
    "2x'te hepsi, 1 sa": (2.0, 1.0, None, None, 1),
    "1,5x'te hepsi, 1 sa": (1.5, 1.0, None, None, 1),
}
CAP = 5.0


def simulate(alerts: list[dict], name: str) -> str:
    alerts = sorted(alerts, key=lambda a: a["t_in"])
    ranks = pd.Series([a["pct"] for a in alerts]).rank(pct=True).values
    med = np.nanmedian([a["depth"] for a in alerts])
    for a, q in zip(alerts, ranks):
        a["size"] = 0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01
        a["depth"] = a["depth"] if np.isfinite(a["depth"]) else med
        a["events"] = {"x": a["legs"][(name, "son")]}
    days = sorted({a["day"] for a in alerts})
    bank = trade_sim.simulate(alerts, "x", 1000, True) / 1000
    per_day = [trade_sim.simulate([a for a in alerts if a["day"] == d], "x", 1000, True) / 1000 for d in days]
    mult = np.array([a["mult"][name] for a in alerts])
    best = int(np.argmax(mult))
    luck = trade_sim.simulate([a for j, a in enumerate(alerts) if j != best], "x", 1000, True) / 1000
    return (f"{len(alerts):3d} seçim · kasa {bank:.2f}x (gün gün {' / '.join(f'{x:.2f}' for x in per_day)}) · "
            f"işlem başı ort {mult.mean():.2f}x / medyan {np.median(mult):.2f}x · en iyi 1 hariç {luck:.2f}x")


def main():
    db = sqlite3.connect(sys.argv[1])
    top = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
    d = prepare(pd.read_parquet(sys.argv[2]), 5, 1, 90)
    d = d[d.obs_h >= HOLD_MIN].reset_index(drop=True)
    sol = pd.read_sql("SELECT ts, usd FROM sol_price ORDER BY ts", db)
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    alerts = []
    for r in d.itertuples():
        a, _ = make_alert(load(db, r.coin, sol), r.ts, data_end, RULES, modes=("son",))
        a["mult"] = {n: sum(sh * p for _, sh, p in a["legs"][(n, "son")]) / a["p_in"] for n in RULES}
        a["day"] = r.day
        alerts.append(a)
    for n in RULES:
        d[n] = [a["mult"][n] for a in alerts]
    days = sorted(d.day.unique())
    print(f"{len(d)} an (5. alıcı, curve <= %90, 3 sa izlenmiş); kural sonucu (Fomo komisyonu öncesi) hepsinde ortalama: "
          + " · ".join(f"{n} {d[n].mean():.2f}x" for n in RULES))
    base, _ = walk_forward(d, days, importance=False)  # the 2x model, for comparison
    base_idx = set(base[base.pct > 1 - top].index)
    for n in RULES:
        rows = []
        for day in days[2:]:
            tr, te = d[d.day < day], d[d.day == day].copy()
            m = HistGradientBoostingRegressor(**PARAMS).fit(tr[FEATURES], np.clip(tr[n], 0, CAP))
            te["pred"] = m.predict(te[FEATURES])
            te["pct"] = te.pred.rank(pct=True)
            rows.append(te)
        t = pd.concat(rows)
        picked = t[t.pct > 1 - top]
        print(f"\n{n}:")
        sel = [dict(alerts[i], pct=picked.pct[i]) for i in picked.index]
        print(f"  kâr modeli  : {simulate(sel, n)}")
        sel = [dict(alerts[i], pct=base.pct[i]) for i in sorted(base_idx)]
        print(f"  2x modeli   : {simulate(sel, n)}")
        print(f"  tahmin ↔ gerçek (test günleri, sıra korelasyonu): {t.pred.corr(t[n], method='spearman'):.3f}")


if __name__ == "__main__":
    main()
