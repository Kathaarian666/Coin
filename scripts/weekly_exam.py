"""Weekly final exam of last week's models under the bot's own exit rule (PROJE.md §0 D8 / B2, §4.12-4.15).

  python scripts/weekly_exam.py <trades.db> <picks.parquet> <exit_truth cache .jsonl> <flags.parquet>

picks: scripts/fresh_test.py --model <last week's model> --bot-bar --picks (cut to the exam week); the cache:
scripts/exit_truth.py's events of those picks (<out>.cache.jsonl); flags: scripts/pick_flags.py (hook of the pick's V4
pool + owner()). Risky pick (as rhscanner.live.risk_check): no hook on its pool, or an owner other than the launchpad's.

Per pick (30 s late buy, prices as scripts/exit_study.Path_), rules side by side:
- bot: everything at 5x (two buys in a row at 5x the alert price), else at 3 h — 15 min for a risky pick (paper.hold5)
- 5x3h: 5x or 3 h for every pick
- yan: half at 5x, the other half 10 min later (paper.paper_trade_10); else as "bot"
- 2x3h: everything at 2x, else at 3 h
The value at a time limit is the on-chain value (scripts/risky_picks.py value_at: last Fomo price x the venue's move,
0 once its liquidity was pulled); an unmeasurable value (the coin changed venue) is 0 (lo) or the Fomo price (hi).
Bank as scripts/exit_study.weeks: $1000, 4/2/1 % by rank thirds, costs (fee + depth slippage); "en iyi hariç" drops the
pick with the best multiple.
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from exit_study import Path_, weeks  # noqa: E402
from security_extra import depth_at  # noqa: E402
from trust_export import flags  # noqa: E402

BPS = 9.93
RULES = ("bot", "5x3h", "yan", "2x3h")


def value_at(e, fomo_blk, fomo_px, exit_blk):
    """Fomo price at the exit x venue ratio (as scripts/risky_picks.py), 0 if pulled, NaN if unmeasurable."""
    before = fomo_blk <= exit_blk
    last_fomo = fomo_blk[before][-1]
    p_fomo = float(np.median(fomo_px[before][-5:]))
    upto = [x for x in e if x[0] <= exit_blk]
    trades = [x for x in upto if x[4] == "trade"]
    at = [x for x in trades if x[0] <= last_fomo]
    if not trades:
        return p_fomo, p_fomo
    if not at or not at[-1][3]:
        return np.nan, p_fomo
    venue = at[-1][2]
    last = [x for x in trades if x[2] == venue][-1]
    pulled = any(x[4] == "pull" and x[2] == venue and x[:2] > last[:2] for x in upto)
    if trades[-1][2] != venue:
        return np.nan, p_fomo
    return (0.0 if pulled else p_fomo * last[3] / at[-1][3]), p_fomo


def first_two(mask):
    hit = np.flatnonzero(mask[1:] & mask[:-1])
    return hit[0] + 1 if len(hit) else None


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)
    p = pd.read_parquet(sys.argv[2]).sort_values("ts").reset_index(drop=True)
    p["coin"] = p.coin.str.lower()
    ev = {t: [tuple(x) for x in e] for t, e in (json.loads(line) for line in open(sys.argv[3]))
          if e is not None} if Path(sys.argv[3]).exists() else {}
    fl = pd.read_parquet(sys.argv[4])
    fl["token"] = fl.token.str.lower()
    f = flags(fl.drop_duplicates("token").set_index("token"))
    p["risky"] = ((f.hook_yok + f.sahip).reindex(p.coin).fillna(0).values > 0)
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    ranks = p.pct.rank(pct=True).values
    alerts, rows = {"lo": [], "hi": []}, []
    for r, q in zip(p.itertuples(), ranks):
        tr = np.array(db.execute("SELECT ts, block, side, usd, amount FROM trades WHERE token = ? ORDER BY ts",
                                 (names[r.coin],)).fetchall(), float)
        ts, blk, side, usd = tr[:, 0], tr[:, 1], tr[:, 2], tr[:, 3]
        px = np.where(tr[:, 4] > 0, usd / np.where(tr[:, 4] > 0, tr[:, 4], 1), np.nan)
        ok = np.isfinite(px)
        path = Path_(ts, px, side, r.ts, data_end)
        ab = blk[ts <= r.ts][-1]
        e = ev.get(r.coin, [])
        bts, bpx = path.ts[path.buys], path.px[path.buys]

        def hit(mult):
            j = first_two(bpx >= mult * path.p_alert)
            return bts[j] if j is not None else np.inf

        def val(t):  # (lo, hi) value at time t
            v, pf = value_at(e, blk[ok], px[ok], ab + int((t - r.ts) * BPS))
            return (0.0 if v != v else v), (pf if v != v else v)

        t5, t2 = hit(5.0), hit(2.0)
        hold = 900 if r.risky else 3 * 3600
        legs = {"lo": {}, "hi": {}}

        def put(rule, parts):  # parts: [(time, share, (lo, hi) price)]
            for i, k in enumerate(("lo", "hi")):
                legs[k][rule] = [(t, sh, pr[i]) for t, sh, pr in parts]

        p5 = (5 * path.p_alert, 5 * path.p_alert)
        put("bot", [(t5, 1.0, p5)] if t5 <= r.ts + hold else [(r.ts + hold, 1.0, val(r.ts + hold))])
        put("5x3h", [(t5, 1.0, p5)] if t5 <= r.ts + 3 * 3600 else [(r.ts + 3 * 3600, 1.0, val(r.ts + 3 * 3600))])
        put("yan", [(t5, 0.5, p5), (t5 + 600, 0.5, val(t5 + 600))] if t5 <= r.ts + hold
            else [(r.ts + hold, 1.0, val(r.ts + hold))])
        p2 = (2 * path.p_alert, 2 * path.p_alert)
        put("2x3h", [(t2, 1.0, p2)] if t2 <= r.ts + 3 * 3600 else [(r.ts + 3 * 3600, 1.0, val(r.ts + 3 * 3600))])
        b = (side == 1) & ok
        depth = depth_at(px[b], usd[b], ts[b], r.ts)
        size = 0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01
        for k in ("lo", "hi"):
            alerts[k].append({"t_in": path.t_in, "p_in": path.p_in, "depth": depth, "ranked": size, "legs": legs[k]})
        rows.append({"coin": r.coin, "ts": r.ts, "risky": r.risky, "pons": bool(r.is_pons), "t5_min": (t5 - r.ts) / 60,
                     **{f"{k}_{rule}": sum(sh * pr for _, sh, pr in legs[k][rule]) / path.p_in
                        for k in ("lo", "hi") for rule in RULES}})
    for k in ("lo", "hi"):
        med = np.nanmedian([a["depth"] for a in alerts[k]])
        for a in alerts[k]:
            if not np.isfinite(a["depth"]):
                a["depth"] = med
    x = pd.DataFrame(rows)
    print(f"{len(p)} seçim · {pd.to_datetime(p.ts.min(), unit='s'):%d %b %H:%M} – "
          f"{pd.to_datetime(p.ts.max(), unit='s'):%d %b %H:%M} · riskli {int(p.risky.sum())} · Pons {int(p.is_pons.sum())}"
          f" · 3 sa'te 5x {int((x.t5_min <= 180).sum())} · 15 dk'da 5x {int((x.t5_min <= 15).sum())}")
    for rule in RULES:
        out = []
        for k in ("lo", "hi"):
            w = weeks(alerts[k], rule, "ranked")
            best = int(np.argmax(x[f"{k}_{rule}"].values))
            wl = weeks([a for i, a in enumerate(alerts[k]) if i != best], rule, "ranked")
            out.append((w, wl))
        fmt = lambda ws: " / ".join(f"{v:.2f}" for v in ws)  # noqa: E731
        print(f"{rule:>5}: kasa/hafta lo {fmt(out[0][0])} · hi {fmt(out[1][0])} · en iyi hariç lo {fmt(out[0][1])} · "
              f"hi {fmt(out[1][1])} · işlem başı ort lo riskli {x[x.risky][f'lo_{rule}'].mean():.2f}x · "
              f"normal {x[~x.risky][f'lo_{rule}'].mean():.2f}x")
    x.to_parquet(Path(sys.argv[2]).with_name(Path(sys.argv[2]).stem + "_exam.parquet"), index=False)


if __name__ == "__main__":
    main()
