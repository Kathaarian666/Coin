"""pump.fun trade simulation of the walk-forward picks (PROJE.md §0 A8, step 3; the twin of scripts/exit_truth_rules.py).

  python scripts/pump_sim.py <solana.db> <pump_study.parquet> [<top share>=0.02] [k=5]

Picks: scripts/pump_rise.py walk-forward model (5th Fomo buyer, 2x within 1 h, coins over 90 % of the curve left
out), the day's top share; only picks with 3 h of data after them. The user's trade as on Robinhood
(scripts/exit_study.py Path_): 30 s late at the last buy price then, Fomo fee (trade_sim) + pump.fun's fee
PUMP_FEE each way + price impact against the venue's SOL reserves, sizes 4/2/1 % of the bankroll by rank.
Exit value, unlike Robinhood, is on-chain truth at every Fomo trade: each pump.fun curve event carries the curve's
reserves after it, which include everyone's trades, and a curve cannot be pulled (on PumpSwap the trade's own price). What is still held at the time limit
is worth the spot price (reserves) of the last Fomo trade before it ("son"); the cautious value ("temkinli") is the
lower of that and the first Fomo trade after it (prices between two Fomo trades are not seen).
The 5x rule was chosen on Robinhood (PROJE.md §4.4c) before looking at pump.fun; the others are for context.
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trade_sim  # noqa: E402
from exit_study import Path_  # noqa: E402
from pump_rise import prepare, walk_forward  # noqa: E402

PUMP_FEE = 0.0125  # pump.fun curve fee per side (PumpSwap's is lower: cautious)
HOLD_MIN = 3  # hours of data a pick needs after it
RULES = {  # (target x alert price, share sold there, stop, trail, hours)
    "5x'te hepsi, 3 sa (Robinhood'da seçilen)": (5.0, 1.0, None, None, 3),
    "Robinhood şimdiki (2x'te yarı, %50/%50), 3 sa": (2.0, 0.5, 0.5, 0.5, 3),
    "2x'te hepsi, 1 sa": (2.0, 1.0, None, None, 1),
    "3x'te hepsi, 1 sa": (3.0, 1.0, None, None, 1),
    "3x'te hepsi, 3 sa": (3.0, 1.0, None, None, 3),
    "5x'te hepsi, 1 sa": (5.0, 1.0, None, None, 1),
    "10x'te hepsi, 3 sa": (10.0, 1.0, None, None, 3),
    # low target, short time (9 Oct, PROJE.md §4.5d: the picks rise fast and fall fast)
    "1,3x'te hepsi, 10 dk": (1.3, 1.0, None, None, 1 / 6),
    "1,5x'te hepsi, 10 dk": (1.5, 1.0, None, None, 1 / 6),
    "2x'te hepsi, 10 dk": (2.0, 1.0, None, None, 1 / 6),
    "1,5x'te hepsi, 30 dk": (1.5, 1.0, None, None, 0.5),
    "1,5x'te hepsi, 1 sa": (1.5, 1.0, None, None, 1),
}


def load(db, mint: str, sol: pd.DataFrame) -> pd.DataFrame:
    g = pd.read_sql("SELECT ts, venue, side, lamports, tokens, vsol, vtok FROM trades WHERE mint = ? AND tokens > 0 "
                    "AND lamports > 0 ORDER BY ts, slot", db, params=(mint,))
    usd = np.interp(g.ts, sol.ts, sol.usd) / 1e9
    g["px"] = g.lamports * usd / g.tokens  # the trade's own price
    # the venue after it: the curve's reserves; PumpSwap's stored reserves sit ~10 % under its own trade prices on
    # both sides (not the post-trade pool state), so there the trade price is used
    g["spot"] = np.where((g.venue == 1) & (g.vtok > 0), g.vsol * usd / g.vtok.where(g.vtok > 0), g.px)
    g["depth"] = g.vsol * usd  # the venue's SOL side in USD
    return g


def main():
    db = sqlite3.connect(sys.argv[1])
    top = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
    k = int(sys.argv[4]) if len(sys.argv) > 4 else 5
    d = prepare(pd.read_parquet(sys.argv[2]), k, 1, 90)
    t, _ = walk_forward(d, sorted(d.day.unique()), importance=False)
    picks = t[(t.pct > 1 - top) & (t.obs_h >= HOLD_MIN)].sort_values("ts")
    sol = pd.read_sql("SELECT ts, usd FROM sol_price ORDER BY ts", db)
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    alerts, stale = [], []
    for r in picks.itertuples():
        g = load(db, r.coin, sol)
        ts, px, side, spot = g.ts.values, g.px.values, g.side.values, g.spot.values
        path = Path_(ts, px, side, r.ts, data_end)
        before = np.flatnonzero(ts <= r.ts)
        a = {"t_in": path.t_in, "p_in": path.p_in * (1 + PUMP_FEE), "pct": r.pct, "day": r.day,
             "depth": float(g.depth.values[before[-1]]) if len(before) else np.nan, "legs": {}}
        for name, rule in RULES.items():
            legs = path.legs(*rule)
            t_end = r.ts + 3600 * rule[4]
            i = np.searchsorted(ts, t_end, side="right") - 1  # last Fomo trade before the limit
            for mode in ("son", "temkinli"):
                out = []
                for when, share, price in legs:
                    if when >= t_end - 1e-6:  # still held at the limit: the venue's spot then
                        price = spot[i]
                        if mode == "temkinli" and i + 1 < len(ts):
                            price = min(price, spot[i + 1])
                    out.append((when, share, price * (1 - PUMP_FEE)))
                a["legs"][(name, mode)] = out
            if rule == (5.0, 1.0, None, None, 3):
                stale.append({"since_last_min": (t_end - ts[i]) / 60,
                              "to_next_min": (ts[i + 1] - t_end) / 60 if i + 1 < len(ts) else np.nan,
                              "next_over_last": spot[i + 1] / spot[i] if i + 1 < len(ts) else np.nan,
                              "hit5": legs[0][0] < t_end - 1e-6 and abs(legs[0][2] / (5 * path.p_alert) - 1) < 1e-9})
        alerts.append(a)
    med = np.nanmedian([a["depth"] for a in alerts])
    ranks = pd.Series([a["pct"] for a in alerts]).rank(pct=True).values
    for a, q in zip(alerts, ranks):
        a["depth"] = a["depth"] if np.isfinite(a["depth"]) else med
        a["size"] = 0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01
    days = sorted({a["day"] for a in alerts})
    s = pd.DataFrame(stale)
    print(f"{k}. alıcı, {len(alerts)} seçim (en iyi %{100 * top:g}, {', '.join(f'{pd.Timestamp(x):%d %b}' for x in days)}); "
          f"5x'e 3 saatte ulaşan {int(s.hit5.sum())}")
    held = s[~s.hit5]
    print(f"3. saatte elde kalanlar ({len(held)}): son Fomo işleminden bu yana medyan {held.since_last_min.median():.1f} dk "
          f"(%{100 * (held.since_last_min > 15).mean():.0f}'i 15 dk'dan eski), sonraki Fomo işlemine medyan "
          f"{held.to_next_min.median():.1f} dk; sonraki / son fiyat medyan {held.next_over_last.median():.2f}\n")
    print(f"{'kural':<48} {'değer':<9} {'toplam':>6} {'gün gün':<26} {'işlem başı ort / medyan':<24} en iyi 1 hariç")
    for name in RULES:
        for mode in ("son", "temkinli"):
            for a in alerts:
                a["events"] = {"x": a["legs"][(name, mode)]}
            bank = trade_sim.simulate(alerts, "x", 1000, True) / 1000
            per_day = [trade_sim.simulate([a for a in alerts if a["day"] == day], "x", 1000, True) / 1000 for day in days]
            mult = np.array([sum(sh * p for _, sh, p in a["legs"][(name, mode)]) / a["p_in"] for a in alerts])
            best = int(np.argmax(mult))
            luck = trade_sim.simulate([a for j, a in enumerate(alerts) if j != best], "x", 1000, True) / 1000
            print(f"{name:<48} {mode:<9} {bank:6.2f}x {' / '.join(f'{x:.2f}' for x in per_day):<26} "
                  f"{mult.mean():5.2f}x / {np.median(mult):4.2f}x{'':<10} {luck:.2f}x")


if __name__ == "__main__":
    main()
