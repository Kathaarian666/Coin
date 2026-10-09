"""pump.fun strategy lab (PROJE.md §4.5e): any Fomo-traded Solana coin, any moment, entry rule -> exit rule, backtested
on chain prices with the user's delay and costs. The pool is every coin Fomo users trade (bonding curve AND graduated
PumpSwap coins, which carry ~86 % of the volume), not only new coins at their 5th Fomo buyer (scripts/pump_study.py).

  python scripts/pump_lab.py build <solana.db> <out.parquet> [<every min>=10]
  python scripts/pump_lab.py grad <grads.parquet> <candles.jsonl> <out.parquet>

build: candidate moments = the first Fomo buy of each coin in each <every>-minute bucket (only what is known then;
no "coins that later ..." universe, PROJE.md §6). Features from the coin's Fomo trades up to that buy: new Fomo buyers
(a wallet's first buy of the coin in the data) and buy/sell $ in the last 5/15/60 min, price change over 5/15/60/240
min, distance from the 24 h high, market cap, curve fill, graduated or not and since when, coin age.
Outcomes, the user's trade: buy 30 s after the moment (DELAY) at the venue price then, sell when a rule fires plus
30 s again; per exit rule in RULES the net multiple of a STAKE-dollar trade (Fomo fee max($0.95, 0.5 %) each way,
venue fee: curve 1.25 %, PumpSwap 0.30 %, price impact stake / venue SOL depth) and the gross multiple (price only).
Prices: on the curve the spot from the curve's reserves after each Fomo trade (they include everyone's trades: chain
truth); on PumpSwap the trade's own price (only pools quoted in SOL). Targets and stops need two trades in a row past
the level (PROJE.md §6 rule 4); at the time limit the lower of the last price before it and the first after it.
Only moments with the longest time limit fully inside the data are kept.
grad: the same on full-market one-minute candles (scripts/pump_fetch.py candles) of coins Fomo saw graduate; moments are
the minutes from the graduation Fomo saw (its first PumpSwap trade; known then, so no "coins that will graduate"
universe) to GRAD_H hours after. Cautious minute execution: the signal is a minute's close, the buy the next minute's
close (~1 min late), a rule fires on a minute's close and sells at the next minute's close; a minute without trades
keeps the last close. Features from the candles up to the signal: minutes since graduation, market cap, returns
1/5/15 min and since graduation, distance from the high since graduation, $ volume 1/5/15 min and since graduation,
active minutes in the last 15. Per rule the price multiple r_ and the exit market cap mo_; grad_net() turns them into
the net multiple of any stake (costs as above with the PumpSwap fee; depth of a fresh PumpSwap pool ~$8.5k SOL side
at ~$54k market cap, growing with the square root of the price: $1000 moves a fresh pool ~12 % each way).
rl_: the same rules as standing orders in the app (no delay on the way out): the target fills at the target when a
minute's high reaches it, the stop at the lower of its level and that minute's close (a minute reaching both: stop).
"""

import sqlite3
import sys

import numpy as np
import pandas as pd

WSOL = "So11111111111111111111111111111111111111112"
CURVE_TOKENS = 793_100_000 * 10**6
SUPPLY = 10**15  # pump.fun: 1B tokens, 6 decimals (raw)
DELAY = 30.0  # s, the user's reaction, on the way in and out
CAUTIOUS = True  # buy at the higher, sell at the lower of the Fomo trades around the moment (prices between are unseen)
STAKE = 50.0  # $ per trade
FOMO_MIN, FOMO_FEE = 0.95, 0.005
VENUE_FEE = {1: 0.0125, 2: 0.003}
WARMUP = 12 * 3600  # s after the data starts before moments count (new-buyer counts need some history)
TPS = (1.3, 1.5, 2.0, 3.0, 5.0)
SLS = (0.25, 0.5)
TRS = (0.3,)
HOLDS = (0.25, 1.0, 4.0, 24.0)  # hours
RULES = [(tp, sl, tr, h) for tp in TPS + (None,) for sl in SLS + (None,) for tr in TRS + (None,) for h in HOLDS]


def rule_name(r) -> str:
    tp, sl, tr, h = r
    return f"tp{tp or '-'}_sl{sl or '-'}_tr{tr or '-'}_h{h:g}"


def load(path: str) -> pd.DataFrame:
    db = sqlite3.connect(path)
    t = pd.read_sql("SELECT slot, ts, venue, mint, side, user, lamports, tokens, vsol, vtok, pool, rtok FROM trades "
                    "WHERE tokens > 0 AND lamports > 0", db)
    pools = pd.read_sql("SELECT pool, quote FROM pools", db).set_index("pool")["quote"]
    sol = pd.read_sql("SELECT ts, usd FROM sol_price ORDER BY ts", db)
    t = t[t.mint != WSOL]
    t = t[(t.venue == 1) | (t.pool.map(pools) == WSOL)]  # PumpSwap pools quoted in SOL only
    t = t.sort_values(["mint", "ts", "slot"], kind="stable").reset_index(drop=True)
    sol_usd = np.interp(t.ts, sol.ts, sol.usd)
    t["usd"] = t.lamports / 1e9 * sol_usd
    px = t.usd / t.tokens
    spot = t.vsol / 1e9 * sol_usd / t.vtok.where(t.vtok > 0)
    t["mark"] = np.where((t.venue == 1) & spot.notna(), spot, px)
    t["depth"] = t.vsol / 1e9 * sol_usd  # the venue's SOL side in $
    t["fill"] = np.where(t.venue == 1, 1 - t.rtok / CURVE_TOKENS, np.nan)
    created = pd.read_sql("SELECT mint, created_ts FROM mints", db).set_index("mint")["created_ts"]
    t["created"] = t.mint.map(created)
    return t


def held(m: np.ndarray, up: bool) -> np.ndarray:
    """Two trades in a row: the level both reached (min for highs, max for lows)."""
    if len(m) < 2:
        return np.full(len(m), -np.inf if up else np.inf)
    out = np.minimum(m[1:], m[:-1]) if up else np.maximum(m[1:], m[:-1])
    return np.concatenate([[-np.inf if up else np.inf], out])


def first(mask: np.ndarray) -> int:
    k = np.flatnonzero(mask)
    return int(k[0]) if len(k) else -1


def fee(v: float) -> float:
    return max(FOMO_MIN, FOMO_FEE * v)


def outcomes(ts, mark, venue, depth, t0, data_end):
    """Per rule (net, gross) of the user's trade at moment t0 (NaN when the rule's time limit is past the data end), or
    None when even the shortest one is."""
    t_in = t0 + DELAY
    if t_in + 3600 * HOLDS[0] > data_end:
        return None
    i = np.searchsorted(ts, t_in, side="right") - 1
    p_in, v_in, d_in = mark[i], venue[i], depth[i]
    if CAUTIOUS and i + 1 < len(ts):  # the price between two Fomo trades is not seen: the worse of the two
        p_in = max(p_in, mark[i + 1])
    if not (p_in > 0):
        return None
    imp_in = STAKE / d_in if d_in > 0 else 0.02
    cost = p_in * (1 + VENUE_FEE[int(v_in)] + imp_in)
    tokens = (STAKE - fee(STAKE)) / cost
    j0 = i + 1
    j1 = np.searchsorted(ts, t_in + 3600 * HOLDS[-1], side="right")
    fts, fm, fv, fd = ts[j0:j1], mark[j0:j1], venue[j0:j1], depth[j0:j1]
    hi, lo = held(fm, True), held(fm, False)
    peak = np.maximum.accumulate(np.maximum(hi, p_in)) if len(fm) else fm

    def sell(t_fire):
        """Price 30 s after a rule fires (the last trade by then)."""
        k = np.searchsorted(fts, t_fire + DELAY, side="right") - 1
        p, v, d = (fm[k], fv[k], fd[k]) if k >= 0 else (p_in, v_in, d_in)
        if CAUTIOUS and k + 1 < len(fts):
            p = min(p, fm[k + 1])
        return p, v, d

    def at_limit(t_end):
        k = np.searchsorted(fts, t_end, side="right") - 1
        p, v, d = (fm[k], fv[k], fd[k]) if k >= 0 else (p_in, v_in, d_in)
        if k + 1 < len(fts):
            p = min(p, fm[k + 1])
        return p, v, d

    t_tp = {tp: (fts[k] if (k := first(hi >= tp * p_in)) >= 0 else np.inf) for tp in TPS}
    t_sl = {sl: (fts[k] if (k := first(lo <= (1 - sl) * p_in)) >= 0 else np.inf) for sl in SLS}
    t_tr = {tr: (fts[k] if (k := first(lo <= (1 - tr) * peak)) >= 0 else np.inf) for tr in TRS}
    out = []
    for tp, sl, tr, h in RULES:
        t_end = t_in + 3600 * h
        if t_end > data_end:
            out.append((np.nan, np.nan))
            continue
        t_fire = min(t_tp[tp] if tp else np.inf, t_sl[sl] if sl else np.inf, t_tr[tr] if tr else np.inf)
        p, v, d = sell(t_fire) if t_fire <= t_end else at_limit(t_end)
        imp = STAKE * p / p_in / d if d > 0 else 0.02
        gross_out = tokens * p * max(0.0, 1 - VENUE_FEE[int(v)] - imp)
        out.append(((gross_out - fee(gross_out)) / STAKE if gross_out > 0 else 0.0, p / p_in))
    return out, p_in, v_in, d_in


def coin_moments(args):
    mint, g, data_start, data_end, every_min = args
    ts, side, usd, mark = g.ts.values.astype(float), g.side.values, g.usd.values, g.mark.values
    venue, depth, fill, users = g.venue.values, g.depth.values, g.fill.values, g.user.values
    seen, new = set(), np.zeros(len(g), bool)
    for k in range(len(g)):
        if side[k] == 1 and users[k] not in seen:
            seen.add(users[k])
            new[k] = True
    buy = side == 1
    cnew, cbuy, csell = (np.concatenate([[0], np.cumsum(x)]) for x in (new, usd * buy, usd * ~buy))
    grad_ts = ts[np.flatnonzero((venue == 2) | (np.nan_to_num(fill, nan=0) >= 0.9999))]
    grad_first = grad_ts[0] if len(grad_ts) else np.inf
    created = g.created.values[0]
    bucket = np.floor(ts / (60 * every_min))
    rows, res, last_bucket = [], [], None
    for k in np.flatnonzero(buy & (ts >= data_start + WARMUP)):
        if bucket[k] == last_bucket:
            continue
        last_bucket = bucket[k]
        t0 = ts[k]
        o = outcomes(ts, mark, venue, depth, t0, data_end)
        if o is None:
            break  # later moments of this coin are even closer to the end
        vals, p_in, v_in, d_in = o
        win = {}
        for w in (5, 15, 60):
            a = np.searchsorted(ts, t0 - 60 * w, side="right")
            win[f"nb{w}"] = cnew[k + 1] - cnew[a]
            win[f"buy{w}"] = cbuy[k + 1] - cbuy[a]
            win[f"sell{w}"] = csell[k + 1] - csell[a]
        for w in (5, 15, 60, 240):
            a = np.searchsorted(ts, t0 - 60 * w, side="right") - 1
            win[f"ret{w}"] = mark[k] / mark[a] if a >= 0 else np.nan
        a = np.searchsorted(ts, t0 - 86400, side="left")
        h24 = held(mark[a:k + 1], True)
        hi24 = max(mark[k], float(np.max(h24))) if k + 1 > a else mark[k]
        rows.append({"mint": mint, "ts": t0, "venue": int(venue[k]), "mark": mark[k], "mcap": mark[k] * SUPPLY,
                     "depth": d_in, "fill": fill[k], "grad": bool(t0 >= grad_first),
                     "grad_age_h": (t0 - grad_first) / 3600 if t0 >= grad_first else np.nan,
                     "seen_h": (t0 - ts[0]) / 3600, "first_in_data": bool(ts[0] > data_start + 3600),
                     "age_h": (t0 - created) / 3600 if created > 0 else np.nan,
                     "buyers_total": cnew[k + 1], "dd24": mark[k] / hi24, "p_in": p_in, "v_in": v_in, **win})
        res.append([v for v, _ in vals] + [x for _, x in vals])
    return rows, res


def build(db_path: str, out_path: str, every_min: float = 10):
    from multiprocessing import Pool
    t = load(db_path)
    data_start, data_end = t.ts.min(), t.ts.max()
    jobs = ((m, g, data_start, data_end, every_min) for m, g in t.groupby("mint", sort=False, observed=True))
    rows, res = [], []
    with Pool() as pool:
        for r, v in pool.imap_unordered(coin_moments, jobs, chunksize=64):
            rows += r
            res += v
    names = [rule_name(r) for r in RULES]
    out = pd.concat([pd.DataFrame(rows), pd.DataFrame(res, columns=[f"n_{n}" for n in names] + [f"g_{n}" for n in names])],
                    axis=1).sort_values("ts", kind="stable").reset_index(drop=True)
    out.to_parquet(out_path, index=False)
    print(f"{len(out)} an, {out.mint.nunique()} coin, {pd.to_datetime(out.ts.min(), unit='s')} – "
          f"{pd.to_datetime(out.ts.max(), unit='s')}")


GRAD_H = 3.0
GRAD_TPS, GRAD_SLS, GRAD_HOLDS = (1.2, 1.3, 1.5, 2.0, 3.0), (0.15, 0.3, 0.5), (5 / 60, 15 / 60, 0.5, 1.0, 3.0)
GRAD_RULES = [(tp, sl, h) for tp in GRAD_TPS + (None,) for sl in GRAD_SLS + (None,) for h in GRAD_HOLDS]
POOL_USD, POOL_MCAP = 8500.0, 54000.0  # a fresh PumpSwap pool: SOL side $ at market cap $ (medians, 3-8 Oct)


def pool_depth(mcap):
    """SOL side of a PumpSwap pool in $: grows with the square root of the price (constant product)."""
    return POOL_USD * np.sqrt(np.maximum(mcap, 1.0) / POOL_MCAP)


def grad_net(r, mcap_in, mcap_out, stake: float):
    """Net multiple of a stake-dollar trade bought at market cap mcap_in and sold at r times the price: Fomo fee each
    way, PumpSwap fee, price impact stake / pool depth (vectorised)."""
    fee_in = np.maximum(FOMO_MIN, FOMO_FEE * stake)
    tokens = (stake - fee_in) / (1 + VENUE_FEE[2] + stake / pool_depth(mcap_in))
    gross = tokens * r
    gross = gross * np.clip(1 - VENUE_FEE[2] - gross / pool_depth(mcap_out), 0, None)
    return np.where(gross > 0, (gross - np.maximum(FOMO_MIN, FOMO_FEE * gross)) / stake, 0.0)


def grad_coin(args):
    mint, t_grad, c = args
    if len(c) < 2:
        return [], []
    c = np.asarray(c, float)
    ts, close, vol = c[:, 0], c[:, 4], c[:, 5]
    if ts[0] > t_grad:  # the candles do not reach back to the graduation (a coin with > 1000 active minutes)
        return [], []
    m = np.arange(np.floor(ts[0] / 60) * 60, ts[-1] + 60, 60)  # every minute, gaps keep the last close
    kk = np.searchsorted(ts, m, side="right") - 1
    px = close[kk]
    have = ts[kk] == m  # a candle in that minute (else no trade: high = low = the last close)
    high, low = np.where(have, c[kk, 2], px), np.where(have, c[kk, 3], px)
    v = np.zeros(len(m))
    v[np.searchsorted(m, ts)] = vol
    cv = np.concatenate([[0], np.cumsum(v)])
    g0 = int(np.searchsorted(m, t_grad, side="left"))
    p_grad = px[g0 - 1] if g0 > 0 else px[0]
    rows, res = [], []
    for i in range(g0, min(len(m) - 2, g0 + int(GRAD_H * 60))):
        p_in = px[i + 1]  # bought at the next minute's close
        if not (p_in > 0):
            continue
        hi = px[g0:i + 1].max()
        f = {"mint": mint, "ts": m[i] + 60, "min_since_grad": i - g0, "mcap": px[i] * 1e9, "mcap_in": p_in * 1e9,
             "ret_grad": px[i] / p_grad, "dd_hi": px[i] / hi, "vol_grad": cv[i + 1] - cv[g0],
             "act15": int((v[max(0, i - 14):i + 1] > 0).sum())}
        for w in (1, 5, 15):
            f[f"ret{w}"] = px[i] / px[max(0, i - w)]
            f[f"vol{w}"] = cv[i + 1] - cv[max(0, i + 1 - w)]
        rows.append(f)
        fut, fhi, flo = px[i + 2:], high[i + 2:], low[i + 2:]
        r_out, mc_out, r_lim = [], [], []
        for tp, sl, h in GRAD_RULES:
            n = int(round(h * 60))
            if i + 1 + n >= len(m):
                r_out.append(np.nan)
                mc_out.append(np.nan)
                r_lim.append(np.nan)
                continue
            w = fut[:n]
            hit = np.zeros(len(w), bool)
            if tp:
                hit |= w >= tp * p_in
            if sl:
                hit |= w <= (1 - sl) * p_in
            j = np.flatnonzero(hit)
            p_out = px[i + 3 + j[0]] if len(j) and i + 3 + j[0] < len(m) else px[i + 1 + n]
            r_out.append(p_out / p_in)
            mc_out.append(p_out * 1e9)
            # standing orders: the target fills at the target once a minute's high reaches it, the stop at the lower
            # of its level and that minute's close; a minute reaching both counts as the stop (cautious)
            up = fhi[:n] >= tp * p_in if tp else np.zeros(n, bool)
            down = flo[:n] <= (1 - sl) * p_in if sl else np.zeros(n, bool)
            ju, jd = (int(np.argmax(x)) if x.any() else n for x in (up, down))
            if jd <= ju and jd < n:
                r_lim.append(min(1 - sl, fut[jd] / p_in))
            elif ju < n:
                r_lim.append(tp)
            else:
                r_lim.append(px[i + 1 + n] / p_in)
        res.append(r_out + mc_out + r_lim)
    return rows, res


def grad_build(grads_path: str, candles_path: str, out_path: str):
    import json
    from multiprocessing import Pool
    grads = pd.read_parquet(grads_path)["ts"]
    jobs = []
    for line in open(candles_path):
        x = json.loads(line)
        if x["mint"] in grads.index:
            jobs.append((x["mint"], float(grads[x["mint"]]), x["candles"]))
    rows, res = [], []
    with Pool() as pool:
        for r, v in pool.imap_unordered(grad_coin, jobs, chunksize=16):
            rows += r
            res += v
    names = [f"tp{tp or '-'}_sl{sl or '-'}_h{h:g}" for tp, sl, h in GRAD_RULES]
    cols = [f"r_{n}" for n in names] + [f"mo_{n}" for n in names] + [f"rl_{n}" for n in names]
    out = pd.concat([pd.DataFrame(rows), pd.DataFrame(res, columns=cols)], axis=1)
    out = out.sort_values("ts", kind="stable").reset_index(drop=True)
    out.to_parquet(out_path, index=False)
    print(f"{len(jobs)} coin, {out.mint.nunique()} mumları mezuniyete uzanan, {len(out)} an")


if __name__ == "__main__":
    if sys.argv[1] == "grad":
        grad_build(*sys.argv[2:5])
    if sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3], *(float(a) for a in sys.argv[4:5]))
