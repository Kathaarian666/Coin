"""Do holder features help the 2x model? (PROJE.md §0 A1)

  python scripts/holder_study.py <trades.db> <winners_h5.parquet> [<first test day>=2026-09-10]

winners_h5 = scripts/transfer_features.py at the 5th buyer (holder columns; empty when the moment is more than 1 h
after the coin's first Fomo trade, known at that moment). The same walk-forward as scripts/rise_study.py
(each day scored by a model trained only on the days before it, bars from the 2 days before), run with the 20
chosen criteria and with the holder criteria added, on the same days. Per selection: 2x rate; for the top 2 %
the user's trade simulation (scripts/fresh_test.py build_alerts: 30 s late, "iz", 4/2/1 %), with and without the
best 1 % of trades, and week by week from a fresh $1000.
"""

import contextlib
import io
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fresh_test  # noqa: E402
import rise_study  # noqa: E402
import trade_sim  # noqa: E402

# fomo_holder_share is left out: it counted wallets whose first Fomo trade came later (future knowledge), and the
# bot cannot know every Fomo wallet's history
HOLDER = ["holders", "holder_growth_10m", "top10_pct", "top1_pct", "dev_pct", "dev_sent_pct", "sniper_pct",
          "transfers_10m"]
TOPS = (0.05, 0.02, 0.01)


def run(df, cols):
    rise_study.CHOSEN = cols
    with contextlib.redirect_stdout(io.StringIO()):
        return rise_study.together(df)


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)
    if len(sys.argv) > 3:
        rise_study.CUT = pd.Timestamp(sys.argv[3]).value / 1e9
    # the bot's criteria exactly (rise_study.CHOSEN would also take holder columns that happen to exist)
    base = json.loads((Path(__file__).resolve().parent.parent / "rhscanner" / "paper_model.json").read_text())["features"]
    df = rise_study.load(sys.argv[2], None, 5)
    have = df.holders.notna().mean()
    print(f"{len(df)} an (5. alıcı, en az 24 saat izlenmiş); holder bilgisi olan %{100 * have:.0f}")
    print("Holder kriterleri tek tek (bilgisi olanlarda; 2x olanlar ↔ olmayanlar, medyan):")
    for c in HOLDER:
        g = df[df[c].notna()]
        print(f"  {c:>18}: 2x {g[g.hit2x][c].median():8.2f} · değil {g[~g.hit2x][c].median():8.2f}")
    sets = {f"{len(base)} kriter (şimdiki)": base, "+ holder": base + [c for c in HOLDER if c not in base]}
    res = {name: run(df, cols) for name, cols in sets.items()}
    days = next(iter(res.values())).day.nunique()
    print(f"\nWalk-forward, {days} test günü ({pd.to_datetime(rise_study.CUT, unit='s'):%d %b}'ten)")
    for top in TOPS:
        for name, r in res.items():
            sel = r[r.pct >= 1 - top]
            rate = sel.hit2x.mean()
            per_day = sel.groupby("day").hit2x.mean()
            print(f"  en iyi %{100 * top:g} {name:>20}: günde {len(sel) / days:4.1f} · 2x %{100 * rate:.1f} "
                  f"(±{196 * np.sqrt(rate * (1 - rate) / len(sel)):.0f}) · gün gün en düşük %{100 * per_day.min():.0f}")
    print("\nEn iyi %2, kullanıcının işlem kuralları (30 sn, iz, 4/2/1 %), $1000:")
    for name, r in res.items():
        sel = r[r.pct >= 0.98].sort_values("ts")
        alerts = fresh_test.build_alerts(db, sel, "pct")
        mult = [sum(sh * p for _, sh, p in a["events"]["iz"]) / a["p_in"] for a in alerts]
        cut = np.quantile(mult, 0.99)
        luck = [a for a, m in zip(alerts, mult) if m < cut]
        print(f"  {name:>20}: tümü {fresh_test.bank_line(alerts)}")
        print(f"  {'':>20}  en iyi %1 hariç {fresh_test.bank_line(luck)}")
        print(f"  {'':>20}  ", end="")
        trade_sim.weekly_view(alerts, days)


if __name__ == "__main__":
    main()
