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
--depth-scale (sensitivity). --fees <pool_depth.parquet>: the venue's own fee + tax (Pons curve 1 % + the coin's tax;
V4 lpFee) is charged on the exit too (fee_factors); without it the exit is valued at Fomo's all-in buy prices.
--v4-fee-floor 0.0148: a V4 pool's fee per side is max(lpFee, this) (hooks take the fee on most Fomo pools; 0.0148 =
half of Fomo's adjacent buy / sell price ratio on V4, PROJE.md §4.16b). --dump <file.parquet>: per pick net $ of both rules (unlimited bankroll). --depth <pool_depth.parquet>: the depth measured on chain (scripts/pool_depth.py) at the
buy, the 5x, 10 min later and the 3 h exit instead (a moment it could not measure falls back to the estimate). paper.net_return's linear impact is too harsh for a $100 trade in a $300 pool.
--risky <flags.parquet> (scripts/risk_flags.py: coin, ts, risky): the bot's rug rule (PROJE.md §0 B4, paper.hold5) — a
risky pick is sold at the 5x only if it comes within --risky-hold s (900 = 15 min), else at the on-chain value then; its
early exit's depth is the buy's measured depth x sqrt(price ratio) (the 3 h depth is the wrong moment), its fee the buy
venue's. --only-pons 0|1: keep only the non-Pons (0) / Pons (1) picks.
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

CHAIN_BPS = {"robinhood": 9.93, "bnb": 2.22}  # blocks per s (BNB: 0.45 s blocks, from the Fomo trades of 3-25 Oct)
BPS = CHAIN_BPS["robinhood"]  # set by --chain / --bps; every block window below uses it
HOLD = 3 * 3600
LATER = 10 * 60
FEE, FEE_MIN = 0.005, 0.95
FEE_GUESS = 0.02  # venue fee + tax per side when unmeasured (the Pons curve's typical 1 % fee + 1 % tax)


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def net(stake, depth, legs, p_in, p_ref, depth_in=None):
    """$ back from `stake`: legs [(share, price)] or [(share, price, depth $ then)]; the fee both ways and price impact
    of a constant-product pool whose quote side was `depth` $ at the price p_ref (the alert) and grows with the square
    root of the price. A depth measured on chain at the buy (depth_in) or at a sale (the leg's third item, NaN /
    None = unknown) replaces the square-root guess there."""
    def at(d, price):
        return d if d is not None and np.isfinite(d) and d > 0 else depth * (price / p_ref) ** 0.5
    coins = (stake - max(FEE_MIN, FEE * stake)) / (p_in * (1 + stake / at(depth_in, p_in)))
    total = 0.0
    for leg in legs:
        share, price = leg[0], leg[1]
        if price <= 0:
            continue
        v = coins * share * price
        v /= 1 + v / at(leg[2] if len(leg) > 2 else None, price)
        total += max(0.0, v - max(FEE_MIN, FEE * v))
    return total


def path_of(tr, t_alert, delay, hold=HOLD):
    ts, blk, side = tr[:, 0], tr[:, 1], tr[:, 2]
    px = np.where(tr[:, 4] > 0, tr[:, 3] / np.where(tr[:, 4] > 0, tr[:, 4], 1), np.nan)
    ok = np.isfinite(px) & (px > 0)
    buy = (side == 1) & ok
    pa = px[buy & (ts <= t_alert)][-1]
    p_in = px[buy & (ts <= t_alert + delay)][-1]
    b = buy & (ts > t_alert + delay) & (ts <= t_alert + hold)
    hit = np.flatnonzero((px[b][1:] >= 5 * pa) & (px[b][:-1] >= 5 * pa))
    ab = int(blk[ts <= t_alert][-1])
    if len(hit):
        return dict(pa=pa, p_in=p_in, ab=ab, t5=float(ts[b][hit[0] + 1]), hb=int(blk[b][hit[0] + 1]))
    eb = ab + int(hold * BPS)
    before = ok & (blk <= eb)
    return dict(pa=pa, p_in=p_in, ab=ab, t5=None, last_fomo=int(blk[before][-1]),
                p_fomo=float(np.median(px[before][-5:])), eb=eb,
                last_px=px[before][-5:], last_buy=side[before][-5:] == 1)


def fee_factors(p, f):
    """Exit price multipliers for the venue's own fee + tax (--fees): Fomo's prices are all-in (a buy's includes the
    buy fee, a sell's is net of the sell fee), so each price is turned into the pool's marginal price by its side and
    the sell fee is charged once. f: {moment: (b, s)}, NaN = unknown → FEE_GUESS (counted). Returns ({leg: factor},
    guessed)."""
    guessed = False
    def bs(m):
        nonlocal guessed
        b, s = f.get(m, (np.nan, np.nan))
        if not (np.isfinite(b) and np.isfinite(s)):
            guessed = True
            return FEE_GUESS, FEE_GUESS
        return b, s
    if p["t5"] is not None:  # the 5x is two Fomo buys at >= 5x: a buy price
        b5, s5 = bs("5x")
        _, sl = bs("later")
        return {"5x": (1 - s5) / (1 + b5), "later": (1 - sl) / (1 + b5)}, guessed
    b, s = bs("exit")
    mid = np.median(np.where(p["last_buy"], p["last_px"] / (1 + b), p["last_px"] / (1 - s)))
    return {"exit": mid / p["p_fomo"] * (1 - s)}, guessed


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
    global BPS
    flags = {"--top", "--delay", "--stake", "--bank", "--target", "--depth-scale", "--depth", "--bps", "--chain",
             "--fees", "--dump", "--v4-fee-floor", "--risky", "--risky-hold", "--only-pons"}
    BPS = arg("--bps", CHAIN_BPS[arg("--chain", "robinhood")])
    args = [a for i, a in enumerate(sys.argv[1:]) if not a.startswith("--") and sys.argv[i] not in flags]
    top, delay = arg("--top", 0.05), arg("--delay", 10)
    stake, bank0, target = arg("--stake", 100.0), arg("--bank", 1000.0), arg("--target", 500.0)
    db = sqlite3.connect(args[0])
    picks = pd.read_parquet(args[1]).sort_values("ts")
    picks["coin"] = picks.coin.str.lower()
    picks = picks[picks.pct >= 1 - top]
    anchor = picks.ts.min()  # weeks start here, also when a filter below drops the first pick (same weeks to compare)
    if "--only-pons" in sys.argv:
        picks = picks[picks.is_pons.astype(bool) == bool(arg("--only-pons", 0))]
    risky, risky_hold = set(), arg("--risky-hold", 900.0)
    if "--risky" in sys.argv:
        rf = pd.read_parquet(sys.argv[sys.argv.index("--risky") + 1])
        risky = {(c.lower(), float(t)) for c, t, r in zip(rf.coin, rf.ts, rf.risky) if r}
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
    real = {}
    if "--depth" in sys.argv:
        dp = pd.read_parquet(sys.argv[sys.argv.index("--depth") + 1])
        real = {(c, t): r for c, t, r in zip(dp.coin, dp.ts, dp.to_dict("records"))}
    fee_tab = {}
    if "--fees" in sys.argv:
        fp = pd.read_parquet(sys.argv[sys.argv.index("--fees") + 1])
        floor = arg("--v4-fee-floor", 0.0)  # hook tax not read on chain: per side at least this on a V4 pool
        for m in ("buy", "5x", "later", "exit"):
            v4 = fp[f"venue_{m}"].notna() & (fp[f"venue_{m}"] != "curve")
            for c in (f"fb_{m}", f"fs_{m}"):
                fp.loc[v4, c] = np.fmax(fp.loc[v4, c].fillna(0.0), floor) if floor else fp.loc[v4, c]
        fee_tab = {(c, t): {m: (r.get(f"fb_{m}", np.nan), r.get(f"fs_{m}", np.nan)) for m in ("buy", "5x", "later", "exit")}
                   for c, t, r in zip(fp.coin, fp.ts, fp.to_dict("records"))}
    fee_guessed = 0
    paths, firsts = {}, {}
    for r in picks.itertuples():
        tr = np.array(db.execute("SELECT ts, block, side, usd, amount FROM trades WHERE token=? ORDER BY ts",
                                 (names[r.coin],)).fetchall(), float)
        is_risky = (r.coin, float(r.ts)) in risky
        paths[r.Index] = path_of(tr, r.ts, delay, risky_hold if is_risky else HOLD)
        paths[r.Index]["risky"] = is_risky
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
    rows, missing, measured = [], 0, 0
    for r in picks.itertuples():
        p = paths[r.Index]
        depth = r.depth_usd if "depth_usd" in picks and np.isfinite(r.depth_usd) and r.depth_usd > 0 else med_depth
        scale = arg("--depth-scale", 1.0)
        depth *= scale
        m = real.get((r.coin, r.ts), {})
        rd = {k: m.get(f"depth_{k}", np.nan) * scale for k in ("buy", "5x", "later", "exit")}
        if m:
            measured += any(np.isfinite(v) for v in rd.values())
        e = ev.get(r.coin)
        ff = {"5x": 1.0, "later": 1.0, "exit": 1.0}
        if "--fees" in sys.argv:
            f = fee_tab.get((r.coin, r.ts), {})
            if p["risky"] and p["t5"] is None:  # the early exit is on the buy's venue
                f = {"exit": f.get("buy", (np.nan, np.nan))}
            got, guessed = fee_factors(p, f)
            ff.update(got)
            fee_guessed += guessed
        if p["t5"] is None:
            px = time_exit(p, e)
            if px is None:
                missing += 1
                continue
            px *= ff["exit"]
            d_exit, t_exit = rd["exit"], r.ts + HOLD
            if p["risky"]:
                d_exit = rd["buy"] * (px / p["p_in"]) ** 0.5 if px > 0 else np.nan
                t_exit = r.ts + risky_hold
            back = net(stake, depth, [(1.0, px, d_exit)], p["p_in"], p["pa"], rd["buy"])
            res = {"5x": (back, t_exit), "yan": (back, t_exit)}
        else:
            p5 = 5 * p["pa"]
            ven = Venue(e, p["hb"]) if e else None
            later = ven.value(p["hb"] + int(LATER * BPS))[0] if ven is not None and ven.ok else 1.0
            res = {"5x": (net(stake, depth, [(1.0, p5 * ff["5x"], rd["5x"])], p["p_in"], p["pa"], rd["buy"]), p["t5"]),
                   "yan": (net(stake, depth, [(0.5, p5 * ff["5x"], rd["5x"]), (0.5, p5 * later * ff["later"], rd["later"])],
                               p["p_in"], p["pa"], rd["buy"]), p["t5"] + LATER)}
        rows.append({"coin": r.coin, "ts": r.ts, "t_in": r.ts + delay, "hit": p["t5"] is not None, "risky": p["risky"],
                     "pons": bool(getattr(r, "is_pons", False)), "res": res})
    first = anchor
    print(f"\nen iyi %{100 * top:g} · tutar ${stake:g} · kasa ${bank0:g}/hafta · alış gecikmesi {delay} sn · hedef "
          f"+${target:g}/hafta · {len(rows)} seçim (zincir verisi olmayan {missing} dışarıda), 3 sa'te 5x {sum(x['hit'] for x in rows)}"
          + (f" · havuz derinliği zincirden: {measured} seçim" if real else " · havuz derinliği tahmin")
          + (f" · havuz ücreti+vergisi çıkışta düşülü (ölçülemeyen {fee_guessed} seçimde %{100 * FEE_GUESS:g} varsayıldı)"
             if "--fees" in sys.argv else "")
          + (f" · riskli {sum(x['risky'] for x in rows)} seçimde 5x süresi {risky_hold / 60:g} dk" if risky else ""))
    for rule in ("5x", "yan"):
        print(f"\n== kural: {'5x olunca hepsini sat' if rule == '5x' else '5x olunca yarısı, kalanı 10 dk sonra'}")
        passed = total = 0
        for wk in range(int((max(x["ts"] for x in rows) - first) // (7 * 86400)) + 1):
            al = [x for x in rows if first + wk * 7 * 86400 <= x["ts"] < first + (wk + 1) * 7 * 86400]
            if not al:
                continue
            # a week is full when the data covers it (not when its last pick is late: a thin filter would look half)
            days = (min(data_end - HOLD - LATER, first + (wk + 1) * 7 * 86400) - (first + wk * 7 * 86400)) / 86400
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
    d = pd.DataFrame([{"coin": x["coin"], "ts": x["ts"], "pons": x["pons"], "hit": x["hit"],
                       "pl": x["res"]["5x"][0] - stake, "pl_yan": x["res"]["yan"][0] - stake} for x in rows])
    if "--dump" in sys.argv:  # one row per traded pick (unlimited bankroll), for weekly tables
        d.to_parquet(sys.argv[sys.argv.index("--dump") + 1], index=False)
    print("\nişlem başı net $ (5x kuralı): " + " · ".join(
        f"{'Pons' if k else 'Pons dışı'} {len(g)} işlem, ort ${g.pl.mean():+.1f}, 5x %{100 * g.hit.mean():.0f}"
        for k, g in d.groupby("pons")))


if __name__ == "__main__":
    main()
