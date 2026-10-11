"""Do full-market criteria help the 2x model? (PROJE.md §4.9; the twin of scripts/holder_study.py)

  python scripts/market_study.py <market features.parquet> [<first test day>=2026-09-10]

The features file: scripts/rh_market.py features (the 5th-buyer rows of winner_study with the m_* criteria: every
trade on the coin's Pons curve and V4 pools up to the moment, not only Fomo's). The same walk-forward as
scripts/rise_study.py (each day scored by a model trained only on the days before it), run with the bot's criteria
and with the full-market ones added, on the same days: per selection the 2x rate, its margin and the worst day.
Profit (the 5x rule on on-chain exit values, scripts/exit_truth.py) only if the selection gets clearly better.
"""

import contextlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rise_study  # noqa: E402

MARKET = ["m_trades", "m_buys", "m_sell_share", "m_trades_5m", "m_buys_5m", "m_fomo_share", "m_minutes",
          "m_same_block_buys", "m_on_curve", "m_buyers", "m_eth_buy", "m_eth_sell", "m_top_buyer_share", "m_buyers_5m"]
TOPS = (0.05, 0.02, 0.01)


def run(df, cols):
    rise_study.CHOSEN = cols
    with contextlib.redirect_stdout(io.StringIO()):
        return rise_study.together(df)


def main():
    if len(sys.argv) > 2:
        rise_study.CUT = pd.Timestamp(sys.argv[2]).value / 1e9
    base = json.loads((Path(__file__).resolve().parent.parent / "rhscanner" / "paper_model.json").read_text())["features"]
    df = rise_study.load(sys.argv[1], None, 5)
    have = df.m_trades.gt(0).mean()
    print(f"{len(df)} an (5. alıcı, en az 24 saat izlenmiş); tüm-pazar işlemi bulunan %{100 * have:.0f}")
    print("Tüm-pazar kriterleri tek tek (2x olanlar ↔ olmayanlar, medyan):")
    for c in MARKET:
        g = df[df[c].notna()]
        print(f"  {c:>18}: 2x {g[g.hit2x][c].median():9.3f} · değil {g[~g.hit2x][c].median():9.3f}")
    sets = {f"{len(base)} kriter (şimdiki)": base, "+ tüm pazar": base + [c for c in MARKET if c not in base]}
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
    for name, r in res.items():
        r.to_parquet(Path(sys.argv[1]).with_name(f"market_wf_{'plus' if 'pazar' in name else 'base'}.parquet"))


if __name__ == "__main__":
    main()
