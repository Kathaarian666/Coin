"""The pick share again, under the 5x rule (PROJE.md §0 B6, 3rd direction): is the band below the bot's top 5 % worth
trading? Every pick of the walk-forward top 10 % (scripts/profit_study.py, k = 5) is traded with the 5x rule:
bought 30 s after the alert, everything sold at the Fomo 5x (two buys in a row), else 3 h after the alert at the
last Fomo price (median of the last 5) x the on-chain ratio, 0 if the venue's liquidity was pulled (exit_truth.py).

  python scripts/share5x.py <trades.db> <top-10 % picks.parquet> <events .jsonl[.gz]> [<last exploration day>=2026-09-30]
                            [--fetch]

--fetch downloads the missing on-chain events from the alert to 3 h after it (exit_truth.venue_prices), appended to
the events file (after5x.py's and exit_truth.py's events work too). Result per pick band (top 2 / 2-5 / 5-10 %):
the brüt multiple per trade (mean, median, without the best trade), 5x share, pulled share; and the weekly bankroll
($1000, sizes 4 / 2 / 1 % by rank thirds inside the selection, brüt) of the top 5 % and the top 10 %.
"""
import gzip
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

BPS = 9.93
DELAY_IN = 30
HOLD = 3 * 3600


def trade_5x(tr, t_alert, ev):
    """(multiple, kind, pulled) of the 5x rule; kind '5x' / 'süre'; None when the time exit has no on-chain data."""
    ts, blk, side = tr[:, 0], tr[:, 1], tr[:, 2]
    px = np.where(tr[:, 4] > 0, tr[:, 3] / np.where(tr[:, 4] > 0, tr[:, 4], 1), np.nan)
    ok = np.isfinite(px) & (px > 0)
    buy = (side == 1) & ok
    pa = px[buy & (ts <= t_alert)][-1]
    p_in = px[buy & (ts <= t_alert + DELAY_IN)][-1]
    b = buy & (ts > t_alert + DELAY_IN) & (ts <= t_alert + HOLD)
    if np.any((px[b][1:] >= 5 * pa) & (px[b][:-1] >= 5 * pa)):
        return 5 * pa / p_in, "5x", False
    if ev is None:
        return None
    eb = blk[ts <= t_alert][-1] + int(HOLD * BPS)
    before = ok & (blk <= eb)
    last_fomo, p_fomo = blk[before][-1], float(np.median(px[before][-5:]))
    upto = [x for x in ev if x[0] <= eb]
    trades = [x for x in upto if x[4] == "trade"]
    at = [x for x in trades if x[0] <= last_fomo]
    if not trades:
        return p_fomo / p_in, "süre", False
    if not at or not at[-1][3] or trades[-1][2] != at[-1][2]:
        return 0.0, "süre", False  # the coin moved venue: unknown, counted as 0 (cautious)
    last = [x for x in trades if x[2] == at[-1][2]][-1]
    pulled = any(x[4] == "pull" and x[2] == at[-1][2] and x[:2] > last[:2] for x in upto)
    return (0.0 if pulled else p_fomo * last[3] / at[-1][3] / p_in), "süre", pulled


def main():
    args = [a for a in sys.argv[1:] if a != "--fetch"]
    db = sqlite3.connect(args[0])
    picks = pd.read_parquet(args[1]).sort_values("ts")
    picks["coin"] = picks.coin.str.lower()
    path = Path(args[2])
    opener = gzip.open if path.suffix == ".gz" else open
    ev = {}
    if path.exists():
        for line in opener(path, "rt"):
            t, e = json.loads(line)
            if len(e) >= len(ev.get(t, [])):
                ev[t] = [tuple(x) for x in e]
    cut = pd.Timestamp(args[3] if len(args) > 3 else "2026-09-30").value / 1e9 + 86400
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    picks = picks[picks.ts + HOLD < data_end]
    trades = {r.coin: np.array(db.execute("SELECT ts, block, side, usd, amount FROM trades WHERE token=? ORDER BY ts",
                                          (names[r.coin],)).fetchall(), float) for r in picks.itertuples()}
    if "--fetch" in sys.argv:
        import exit_truth as et
        curves = dict(db.execute("SELECT lower(token), lower(curve) FROM launches"))
        todo = []
        for r in picks.itertuples():
            tr = trades[r.coin]
            if trade_5x(tr, r.ts, None) is None and r.coin not in ev:
                ab = int(tr[tr[:, 0] <= r.ts][-1, 1])
                todo.append((r.coin, curves.get(r.coin), ab, int(tr[0, 1]), ab + int((HOLD + 300) * BPS)))
        print(f"zincir olayları: {len(todo)} coin indirilecek", flush=True)
        t0 = time.time()
        with ThreadPoolExecutor(4) as pool, opener(path, "at") as out:
            for n, done in enumerate(as_completed([pool.submit(et.one, j) for j in todo])):
                token, e, err = done.result()
                if e is not None:
                    ev[token] = [tuple(x) for x in e]
                    out.write(json.dumps([token, e]) + "\n")
                    out.flush()
                if n % 25 == 0:
                    print(f"  {n}/{len(todo)} · {time.time() - t0:.0f} sn", flush=True)
    rows = []
    for r in picks.itertuples():
        res = trade_5x(trades[r.coin], r.ts, ev.get(r.coin))
        if res is None:
            continue
        rows.append({"ts": r.ts, "pct": r.pct, "x": res[0], "kind": res[1], "pulled": res[2], "explore": r.ts < cut})
    df = pd.DataFrame(rows)
    df["band"] = np.where(df.pct >= 0.98, "en iyi %2", np.where(df.pct >= 0.95, "%2-5", "%5-10"))
    print(f"{len(df)} seçim ölçüldü ({len(picks) - len(df)} zincir verisi yok, dışarıda)")
    for part, g in df.groupby(~df.explore):
        print(f"\n== {'final sınavı (Ekim)' if part else 'keşif (Eylül)'}")
        for band, h in g.groupby("band"):
            x = h.x.sort_values()
            print(f"  {band:10s} n {len(h):4d} · işlem başı ort {x.mean():.2f}x · medyan {x.median():.2f} · en iyi hariç "
                  f"{x.iloc[:-1].mean():.2f} · 5x %{100 * (h.kind == '5x').mean():.0f} · çekilmiş %{100 * h.pulled.mean():.0f}")
        for share in (0.05, 0.10):
            sel = g[g.pct >= 1 - share].sort_values("ts")
            q = sel.pct.rank(pct=True)
            size = np.where(q > 2 / 3, 0.04, np.where(q > 1 / 3, 0.02, 0.01))
            wk = ((sel.ts - g.ts.min()) // (7 * 86400)).astype(int).values
            out = []
            for w in sorted(set(wk)):
                bank = 1000.0
                for s, x in zip(size[wk == w], sel.x.values[wk == w]):
                    bank += bank * s * (x - 1)
                out.append(bank / 1000)
            print(f"  en iyi %{100 * share:g}: günde {len(sel) / g.ts.apply(lambda t: int(t // 86400)).nunique():.1f} seçim · "
                  f"hafta hafta kasa (brüt) {' / '.join(f'{b:.2f}x' for b in out)}")


if __name__ == "__main__":
    main()
