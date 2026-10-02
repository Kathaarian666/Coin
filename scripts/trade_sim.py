"""Trade simulation (PROJE.md step 3): what would following the alerts have done to a bankroll?

  python scripts/trade_sim.py <trades.db> <winners.parquet> <security.parquet> [<first test day>=2026-09-26]

Alerts: the walk-forward model of scripts/rise_study.py (each day scored by a model trained only on the days
before it, bars from the 2 days before). User's rules (PROJE.md §1):
- size: share of the current bankroll by the model's rank inside the selection: top third 4 %, middle 2 %, rest 1 %
- entry at the alert price (the last buy), or DELAYS seconds later at the last buy price then (the reaction time)
- 2x = two buys in a row at >= 2x the alert price (the bot's "2x oldu") → half is sold at 2x
- stop: two trades in a row (buys or sells) at <= half the buy price before the 2x → everything sold at that price
- prices capped at 100x the alert price (PROJE.md §6); luck check: the "iz" rule without the best 1 % of trades
- the other half after a 2x, three rules side by side: "iz": sold once two trades in a row are <= half of the
  highest price held so far (two buys) · "24s": sold at the last price 24 h after the alert · "tut": never sold,
  valued at the last price when the data ends (no trade for 6 h = dead coin, half price)
- an alert with neither 2x nor stop is held to the data end like "tut"
- costs (masraflı): Fomo fee max($0.95, 0.5 %) each way, plus price impact from the pool depth estimated from the
  buys before the alert (scripts/security_extra.py depth_at; constant product, depth per side R: buying x pays
  ~(1 + x/R), selling gets ~(1 - x/R)). brüt = no costs.
Positions run at the same time; the bankroll is updated in time order (sizes use the bankroll at entry).
"""

import contextlib
import heapq
import io
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rise_study  # noqa: E402
from security_extra import depth_at  # noqa: E402

FEE_MIN, FEE = 0.95, 0.005
DEAD = 6 * 3600
BANKS = (250, 1000, 5000)
BARS = (0.10, 0.05, 0.02, 0.01)
RULES = ("iz", "24s", "tut")
CAP = 100.0
DELAYS = (0, 10, 20, 30, 60, 180)  # seconds between the alert and the user's buy
WEEKLY_DELAY = 30  # the user's reaction time (PROJE.md §1)


def two_in_row(mask):
    hit = np.flatnonzero(mask[:-1] & mask[1:])
    return hit[0] + 1 if len(hit) else None  # index of the confirming trade


def path_events(ts, px, side, t_in, p_in, p_alert, data_end):
    """Exit plan of one position bought at t_in for p_in: ({rule: [(time, share, price)]}, "2x" | "stop" | "yok").
    The 2x is the bot's "2x oldu" (2x the alert price), the stop is the user's -50 % (half the buy price)."""
    after = (ts > t_in) & np.isfinite(px) & (px > 0)
    ts, px, side = ts[after], np.minimum(px[after], CAP * p_alert), side[after]  # rule 6: at most 100x per coin
    buys = side == 1
    bts, bpx = ts[buys], px[buys]
    j = two_in_row(bpx >= 2 * p_alert)
    t2x = bts[j] if j is not None else np.inf
    k = two_in_row(px <= 0.5 * p_in)
    tstop = ts[k] if k is not None else np.inf

    def price_at(t):
        i = np.searchsorted(ts, t, side="right") - 1
        if i < 0:
            return p_in
        p = float(np.median(px[max(0, i - 4):i + 1]))  # median of the last 5 trades: ~5 % of sell prices are broken
        return p / 2 if t - ts[i] > DEAD else p  # dead coin: half price (PROJE.md §6)

    end = (data_end, 1.0, price_at(data_end))
    if tstop < t2x:  # the stop came first: everything out
        return {r: [(tstop, 1.0, px[k])] for r in RULES}, "stop"
    if not np.isfinite(t2x):
        return {r: [end] for r in RULES}, "yok"
    first = (t2x, 0.5, 2 * p_alert)
    rest = lambda t, p: (t, 0.5, p)  # noqa: E731
    # iz: trailing stop at half of the highest price held for two buys in a row
    peak, prev_buy, below, trail = 2 * p_alert, None, 0, None
    later = ts > t2x
    for t, p, s in zip(ts[later], px[later], side[later]):
        if s == 1:
            if prev_buy is not None:
                peak = max(peak, min(prev_buy, p))
            prev_buy = p
        below = below + 1 if p <= 0.5 * peak else 0
        if below == 2:
            trail = rest(t, p)
            break
    t24 = min(max(t_in + 86400, t2x), data_end)
    return {"iz": [first, trail or rest(data_end, end[2])],
            "24s": [first, rest(t24, price_at(t24))],
            "tut": [first, rest(data_end, end[2])]}, "2x"


def simulate(alerts, rule, bank0, costs):
    """Bankroll at the end; entries and exits processed in time order."""
    heap, n, bank = [], 0, bank0
    for a in alerts:
        heapq.heappush(heap, (a["t_in"], n, a, None))
        n += 1
    while heap:
        t, _, a, leg = heapq.heappop(heap)
        if leg is None:  # entry
            stake = bank * a["size"]
            fee = max(FEE_MIN, FEE * stake) if costs else 0.0
            if stake <= fee:
                continue
            fill = a["p_in"] * (1 + stake / a["depth"]) if costs else a["p_in"]
            coins = (stake - fee) / fill
            bank -= stake
            for when, share, price in a["events"][rule]:
                heapq.heappush(heap, (when, n, a, (coins * share, price)))
                n += 1
        else:
            coins, price = leg
            value = coins * price
            if costs:
                value *= max(0.0, 1 - value / a["depth"])
                value = max(0.0, value - max(FEE_MIN, FEE * value))
            bank += value
    return bank


def weekly_view(alerts, days):
    """Each test week simulated alone from a fresh bankroll, so a hot early market cannot compound into later
    weeks; rule "iz", WEEKLY_DELAY seconds."""
    first = min(a["t_in"] for a in alerts)
    weeks = {}
    for a in alerts:
        weeks.setdefault(int((a["t_in"] - first) // (7 * 86400)), []).append(a)
    line = []
    for wk, al in sorted(weeks.items()):
        start = pd.to_datetime(first + wk * 7 * 86400, unit="s")
        n_days = min(7.0, (max(a["t_in"] for a in al) - (first + wk * 7 * 86400)) / 86400 + 1)
        if n_days < 3:
            continue  # a stub of a week says nothing
        g, gc = simulate(al, "iz", 1000, False) / 1000, simulate(al, "iz", 1000, True) / 1000
        line.append(f"{start:%d %b}: brüt {g:.2f}x, masraflı $1000 {gc:.2f}x ({len(al)} işlem)")
    print(f"{'hafta hafta (iz, ' + str(WEEKLY_DELAY) + ' sn)':>24} " + " · ".join(line))


def main():
    db_path, winners, security = sys.argv[1], sys.argv[2], sys.argv[3]
    if len(sys.argv) > 4:
        rise_study.CUT = pd.Timestamp(sys.argv[4]).value / 1e9
    df = rise_study.load(winners, security, 3)
    with contextlib.redirect_stdout(io.StringIO()):
        res = rise_study.together(df)
    db = sqlite3.connect(db_path, timeout=60)
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    days = res.day.nunique()
    print(f"Test: {days} gün ({pd.to_datetime(res.ts.min(), unit='s'):%d %b} – {pd.to_datetime(res.ts.max(), unit='s'):%d %b}), "
          f"{len(res)} yeni coin. Getiri = test sonunda kasa / başlangıç; haftalık = bileşik haftalığa çevrilmiş.\n")
    trades = {}
    for bar in BARS:
        sel = res[res.pct >= 1 - bar].sort_values("ts")
        if len(sel) < 5:
            continue
        print(f"== En iyi %{100 * bar:g}: günde {len(sel) / days:.1f} bildirim")
        print(f"{'':>24} {'brüt':>16} " + " ".join(f"{'masraflı $' + str(b):>16}" for b in BANKS))
        for delay in DELAYS:
            alerts = []
            for r in sel.itertuples():
                if r.coin not in trades:
                    g = pd.read_sql("SELECT ts, side, usd, amount FROM trades WHERE token = ? ORDER BY ts", db,
                                    params=(names[r.coin],))
                    px = np.where(g.amount > 0, g.usd / g.amount.where(g.amount > 0), np.nan)
                    trades[r.coin] = (g.ts.values, px, g.side.values, g.usd.values)
                ts, px, side, usd = trades[r.coin]
                b = (side == 1) & np.isfinite(px)
                p_alert = px[b & (ts <= r.ts)][-1]
                t_in = r.ts + delay
                p_in = px[b & (ts <= t_in)][-1]  # the last price the user can see when buying
                ev, kind = path_events(ts, px, side, t_in, p_in, p_alert, data_end)
                alerts.append(dict(t_in=t_in, p_in=p_in, depth=depth_at(px[b], usd[b], ts[b], r.ts), events=ev,
                                   kind=kind, pct=r.pct))
            med_depth = np.nanmedian([a["depth"] for a in alerts])
            ranks = pd.Series([a["pct"] for a in alerts]).rank(pct=True)
            for a, q in zip(alerts, ranks):
                a["size"] = 0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01
                if not np.isfinite(a["depth"]):
                    a["depth"] = med_depth
            if delay == 0:
                print(f"{'':>24} 2x %{100 * np.mean([a['kind'] == '2x' for a in alerts]):.0f} · "
                      f"%50 zarar-kes %{100 * np.mean([a['kind'] == 'stop' for a in alerts]):.0f}")
            rules = RULES if delay == 0 else ("iz",)
            for rule in rules:
                rows = [(f"{rule}, gecikme {delay} sn", alerts)]
                if delay == 0 and rule == "iz":  # luck check: without the best 1 % of the trades
                    mult = [sum(sh * p for _, sh, p in a["events"][rule]) / a["p_in"] for a in alerts]
                    cut = np.quantile(mult, 0.99)
                    rows.append((f"{rule}, en iyi %1 hariç", [a for a, m in zip(alerts, mult) if m < cut]))
                for label, al in rows:
                    cells = []
                    for costs, bank0 in [(False, 1000)] + [(True, b) for b in BANKS]:
                        g = simulate(al, rule, bank0, costs) / bank0
                        cells.append(f"{g:5.2f}x (hf {g ** (7 / days) if g > 0 else 0:4.2f}x)")
                    print(f"{label:>24} " + " ".join(f"{c:>16}" for c in cells))
            if delay == WEEKLY_DELAY:  # the honest view: every week on its own, bankroll reset to $1000
                weekly_view(alerts, days)
        print()


if __name__ == "__main__":
    main()
