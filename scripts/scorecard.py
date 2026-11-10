"""The standard exam every method goes through (PROJE.md "Test ölçütü", user 10 Nov): a weekly bankroll of BANK $, a
fixed STAKE $ per trade, bought DELAY s after the alert, costs included; a week passes with a net profit >= TARGET $.

  python scripts/scorecard.py <trades.db> <picks.parquet> <events .jsonl> [--fetch] [--top 0.05] [--delay 10]
                              [--stake 100] [--bank 1000] [--target 500]

picks: alerts on days the model had not seen (walk-forward: scripts/profit_study.py; fresh_test.py --picks) with coin,
ts, pct. events: on-chain events of the picks (exit_truth.venue_prices; --fetch downloads the missing ones from the
alert to 3 h 15 min after it, which covers both rules). Rules:
- 5x: everything sold at the Fomo 5x (two buys in a row at >= 5x the alert price), else 3 h after the alert at the
  last Fomo price x the on-chain ratio (0 once the venue's liquidity was pulled or the coin moved venue)
- yan: half at the 5x, the rest 10 min later at the on-chain value then (0 if pulled / moved)
Costs: Fomo's fee each way (0.5 %, at least $0.95) and price impact: a constant-product pool with depth_usd of the
pick (estimated from Fomo trades before the alert; unknown = the picks' median) on its quote side at the alert, x
--depth-scale (sensitivity). paper.net_return's linear impact is too harsh for a $100 trade in a $300 pool.
Bankroll: every week starts with BANK; a pick is traded only if STAKE of free cash is there (money comes back when the
position is sold); the week's profit = cash at its end - BANK. "sınırsız" = every pick traded (no cash limit).
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from after5x import Venue  # noqa: E402

BPS = 9.93
HOLD = 3 * 3600
LATER = 10 * 60
FEE, FEE_MIN = 0.005, 0.95


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def net(stake, depth, legs, p_in, p_ref):
    """$ back from `stake`: legs [(share, price)]; the fee both ways and price impact of a constant-product pool whose
    quote side was `depth` $ at the price p_ref (the alert) and grows with the square root of the price."""
    coins = (stake - max(FEE_MIN, FEE * stake)) / (p_in * (1 + stake / (depth * (p_in / p_ref) ** 0.5)))
    total = 0.0
    for share, price in legs:
        if price <= 0:
            continue
        v = coins * share * price
        v /= 1 + v / (depth * (price / p_ref) ** 0.5)
        total += max(0.0, v - max(FEE_MIN, FEE * v))
    return total


def path_of(tr, t_alert, delay):
    ts, blk, side = tr[:, 0], tr[:, 1], tr[:, 2]
    px = np.where(tr[:, 4] > 0, tr[:, 3] / np.where(tr[:, 4] > 0, tr[:, 4], 1), np.nan)
    ok = np.isfinite(px) & (px > 0)
    buy = (side == 1) & ok
    pa = px[buy & (ts <= t_alert)][-1]
    p_in = px[buy & (ts <= t_alert + delay)][-1]
    b = buy & (ts > t_alert + delay) & (ts <= t_alert + HOLD)
    hit = np.flatnonzero((px[b][1:] >= 5 * pa) & (px[b][:-1] >= 5 * pa))
    ab = int(blk[ts <= t_alert][-1])
    if len(hit):
        return dict(pa=pa, p_in=p_in, ab=ab, t5=float(ts[b][hit[0] + 1]), hb=int(blk[b][hit[0] + 1]))
    eb = ab + int(HOLD * BPS)
    before = ok & (blk <= eb)
    return dict(pa=pa, p_in=p_in, ab=ab, t5=None, last_fomo=int(blk[before][-1]),
                p_fomo=float(np.median(px[before][-5:])), eb=eb)


def time_exit(p, ev):
    """Price at the 3 h exit (None = no on-chain data)."""
    if ev is None:
        return None
    upto = [x for x in ev if x[0] <= p["eb"]]
    trades = [x for x in upto if x[4] == "trade"]
    at = [x for x in trades if x[0] <= p["last_fomo"]]
    if not trades:
        return p["p_fomo"]
    if not at or not at[-1][3] or trades[-1][2] != at[-1][2]:
        return 0.0
    last = [x for x in trades if x[2] == at[-1][2]][-1]
    pulled = any(x[4] == "pull" and x[2] == at[-1][2] and x[:2] > last[:2] for x in upto)
    return 0.0 if pulled else p["p_fomo"] * last[3] / at[-1][3]


def main():
    flags = {"--top", "--delay", "--stake", "--bank", "--target", "--depth-scale"}
    args = [a for i, a in enumerate(sys.argv[1:]) if not a.startswith("--") and sys.argv[i] not in flags]
    top, delay = arg("--top", 0.05), arg("--delay", 10)
    stake, bank0, target = arg("--stake", 100.0), arg("--bank", 1000.0), arg("--target", 500.0)
    db = sqlite3.connect(args[0])
    picks = pd.read_parquet(args[1]).sort_values("ts")
    picks["coin"] = picks.coin.str.lower()
    picks = picks[picks.pct >= 1 - top]
    path = Path(args[2])
    opener = gzip.open if path.suffix == ".gz" else open
    ev = {}
    if path.exists():
        for line in opener(path, "rt"):
            t, e = json.loads(line)
            if len(e) >= len(ev.get(t, [])):
                ev[t] = [tuple(x) for x in e]
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    picks = picks[picks.ts + HOLD + LATER < data_end]
    med_depth = float(np.nanmedian(picks.depth_usd)) if "depth_usd" in picks else 3000.0
    paths, firsts = {}, {}
    for r in picks.itertuples():
        tr = np.array(db.execute("SELECT ts, block, side, usd, amount FROM trades WHERE token=? ORDER BY ts",
                                 (names[r.coin],)).fetchall(), float)
        paths[r.Index] = path_of(tr, r.ts, delay)
        firsts[r.Index] = int(tr[0, 1])
    if "--fetch" in sys.argv:
        import exit_truth as et
        curves = dict(db.execute("SELECT lower(token), lower(curve) FROM launches"))
        need = int((HOLD + LATER + 300) * BPS)
        todo = [(r.coin, curves.get(r.coin), paths[r.Index]["ab"], firsts[r.Index], paths[r.Index]["ab"] + need)
                for r in picks.itertuples() if r.coin not in ev]
        print(f"zincir olayları: {len(todo)} coin indirilecek", flush=True)
        t0 = time.time()
        with ThreadPoolExecutor(4) as pool, opener(path, "at") as out:
            for n, done in enumerate(as_completed([pool.submit(et.one, j) for j in todo])):
                token, e, err = done.result()
                if e is not None:
                    ev[token] = [tuple(x) for x in e]
                    out.write(json.dumps([token, e]) + "\n")
                    out.flush()
                if n % 50 == 0:
                    print(f"  {n}/{len(todo)} · {time.time() - t0:.0f} sn", flush=True)
    rows, missing = [], 0
    for r in picks.itertuples():
        p = paths[r.Index]
        depth = r.depth_usd if "depth_usd" in picks and np.isfinite(r.depth_usd) and r.depth_usd > 0 else med_depth
        depth *= arg("--depth-scale", 1.0)
        e = ev.get(r.coin)
        if p["t5"] is None:
            px = time_exit(p, e)
            if px is None:
                missing += 1
                continue
            back = net(stake, depth, [(1.0, px)], p["p_in"], p["pa"])
            res = {"5x": (back, r.ts + HOLD), "yan": (back, r.ts + HOLD)}
        else:
            p5 = 5 * p["pa"]
            ven = Venue(e, p["hb"]) if e else None
            later = ven.value(p["hb"] + int(LATER * BPS))[0] if ven is not None and ven.ok else 1.0
            res = {"5x": (net(stake, depth, [(1.0, p5)], p["p_in"], p["pa"]), p["t5"]),
                   "yan": (net(stake, depth, [(0.5, p5), (0.5, p5 * later)], p["p_in"], p["pa"]), p["t5"] + LATER)}
        rows.append({"ts": r.ts, "t_in": r.ts + delay, "hit": p["t5"] is not None,
                     "pons": bool(getattr(r, "is_pons", False)), "res": res})
    first = min(x["ts"] for x in rows)
    print(f"\nen iyi %{100 * top:g} · tutar ${stake:g} · kasa ${bank0:g}/hafta · alış gecikmesi {delay} sn · hedef "
          f"+${target:g}/hafta · {len(rows)} seçim (zincir verisi olmayan {missing} dışarıda), 3 sa'te 5x {sum(x['hit'] for x in rows)}")
    for rule in ("5x", "yan"):
        print(f"\n== kural: {'5x olunca hepsini sat' if rule == '5x' else '5x olunca yarısı, kalanı 10 dk sonra'}")
        passed = total = 0
        for wk in range(int((max(x["ts"] for x in rows) - first) // (7 * 86400)) + 1):
            al = [x for x in rows if first + wk * 7 * 86400 <= x["ts"] < first + (wk + 1) * 7 * 86400]
            if not al:
                continue
            days = (max(x["ts"] for x in al) - (first + wk * 7 * 86400)) / 86400
            cash, open_, done, skipped = bank0, [], [], 0
            for x in al:  # in time order
                for o in [o for o in open_ if o[0] <= x["t_in"]]:
                    cash += o[1]
                    open_.remove(o)
                if cash < stake:
                    skipped += 1
                    continue
                cash -= stake
                back, t_out = x["res"][rule]
                open_.append((t_out, back))
                done.append(back - stake)
            cash += sum(o[1] for o in open_)
            profit = cash - bank0
            allp = [x["res"][rule][0] - stake for x in al]
            best_out = profit - max(done) if done else 0.0
            full = days >= 6
            total += full
            passed += full and profit >= target
            a = pd.Timestamp(first + wk * 7 * 86400, unit="s")
            print(f"  {a:%d %b} haftası{'' if full else f' (yarım, {days:.0f} gün)'}: {len(al)} seçim, işlem {len(done)} "
                  f"(para yetmeyen {skipped}) · net kâr ${profit:+.0f} · en iyi işlem hariç ${best_out:+.0f} · "
                  f"kârlı işlem %{100 * np.mean([d > 0 for d in done]) if done else 0:.0f} · sınırsız kasayla ${sum(allp):+.0f} "
                  f"→ {'GEÇTİ' if profit >= target else 'KALDI'}")
        print(f"  tam haftalar: {passed}/{total} hedefi geçti")
    d = pd.DataFrame([{"pons": x["pons"], "hit": x["hit"], "pl": x["res"]["5x"][0] - stake} for x in rows])
    print("\nişlem başı net $ (5x kuralı): " + " · ".join(
        f"{'Pons' if k else 'Pons dışı'} {len(g)} işlem, ort ${g.pl.mean():+.1f}, 5x %{100 * g.hit.mean():.0f}"
        for k, g in d.groupby("pons")))


if __name__ == "__main__":
    main()
