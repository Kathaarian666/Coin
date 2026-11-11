"""The real pool depth of the picks, read on chain (PROJE.md devir, iş 1): replaces scorecard.py's depth_usd estimate
(from the price steps of Fomo's own buys) with the reserves of the venue Fomo trades on.

  python scripts/pool_depth.py <trades.db> <picks.parquet> <out.parquet> [--top 0.05] [--delay 10] [--probe]

depth = the venue's quote side in $ (what scorecard.net calls depth: a buy of x $ moves a constant-product price by
(1 + x / depth)^2), at the blocks scorecard.py trades at: the buy (alert + delay), the 5x (Fomo's 5x buy), 10 min
after the 5x (the "yan" rule's second half) and the 3 h exit when there is no 5x. Venue = where the last on-chain trade
at or before the block happened (Pons curve or a V4 pool of the coin).
- V4 pool: the in-range liquidity L and sqrtPriceX96 after the block (Initialize, then every Swap sets L / price /
  tick, a ModifyLiquidity whose range holds the current tick adds its delta) → the token's virtual reserve
  x = L * 2^96 / sqrtP (token = currency0) or L * sqrtP / 2^96; quote depth $ = x * the $ per raw token then.
- Pons curve: the curve's events carry no reserves. A constant-product curve with virtual reserves (x * y = k, like
  pump.fun) is fitted to every CurveBuy / CurveSell since the launch: y before each trade = y0 + the net eth in so far,
  each trade gives k (buy: dt * y * (y + de) / de, sell: dt * y^2 / de - dt * y); y0 is the value where the k's agree
  best. de is net of the curve's fee and tax (curve_trades). fit_spread = the k's spread (median |log k - log k_med|): ~0 means the curve really is constant product.
  --probe prints the raw data of a few curve events first (word count: a curve that logs its reserves would show it).
Fee: fb_m / fs_m = the venue's fee (+ tax) per $ on a buy / sell at the moment (curve: median of the coin's last
FEE_N buys / sells, the tax is a per-coin setting; V4: lpFee from Initialize, NaN for a dynamic fee; a hook's own tax
is not read). A curve with fit_spread > BAD_FIT gets no depth (the scorecard falls back to the estimate).
$ per raw token: the last Fomo trade's usd / amount at or before the block (at the 5x: 5 x the alert price).
Columns: coin, ts, then per moment m in (buy, 5x, later, exit): venue_m ('curve' / pool id / None), depth_m ($),
plus fit_spread / y0 for curve coins. Cache <out>.cache.jsonl keeps the downloaded events (restartable).
"""
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scorecard  # noqa: E402
from scorecard import HOLD, LATER, arg, path_of  # noqa: E402

Q96 = 2 ** 96
FEE_N = 20  # trades per side behind a moment's fee + tax rate
BAD_FIT = 0.005  # fit_spread above this: the curve depth is not trusted (falls back to the estimate)
DYNAMIC_FEE = 0x800000
MOMENTS = ("buy", "5x", "later", "exit")


def signed(word_hex, bits=256):
    v = int(word_hex, 16)
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


def words(data):
    return [data[2 + 64 * i: 2 + 64 * (i + 1)] for i in range((len(data) - 2) // 64)]


# --- pure maths (tests/test_pool_depth.py) ---

def v4_token_reserve(liquidity, sqrt_p, token_is_0):
    """Virtual token reserve (raw) of a V4 pool's in-range liquidity."""
    if not sqrt_p or not liquidity:
        return 0.0
    return liquidity * Q96 / sqrt_p if token_is_0 else liquidity * sqrt_p / Q96


def curve_ks(trades, y0):
    """k per trade of a constant-product curve whose quote reserve starts at y0; trades [(is_buy, eth, tokens)]."""
    y, ks = float(y0), []
    for buy, de, dt in trades:
        if de <= 0 or dt <= 0 or y <= 0:
            ks.append(np.nan)
        elif buy:
            ks.append(dt * y * (y + de) / de)
        else:
            ks.append(dt * y * y / de - dt * y)
        y += de if buy else -de
    return np.array(ks)


def fit_curve(trades):
    """(y0, k, spread) of the constant-product curve that fits the trades best (None if too few trades)."""
    if len(trades) < 3:
        return None
    def spread(y0):
        lk = np.log(curve_ks(trades, y0))
        lk = lk[np.isfinite(lk)]
        return np.median(np.abs(lk - np.median(lk))) if len(lk) >= 3 else np.inf
    out_max = max(1.0, max(-sum(de if b else -de for b, de, _ in trades[:i + 1]) for i in range(len(trades))))
    grid = np.geomspace(out_max * 1.01, out_max * 1e9 + 1e24, 400)
    best = min(grid, key=spread)
    fine = np.geomspace(best / 1.05, best * 1.05, 200)
    best = min(fine, key=spread)
    ks = curve_ks(trades, best)
    return float(best), float(np.nanmedian(ks)), float(spread(best))


def curve_token_reserve(trades, y0, k, upto):
    """Virtual token reserve after the trades with index < upto."""
    y = y0 + sum(de if b else -de for b, de, _ in trades[:upto])
    return k / y if y > 0 else 0.0


class Pool:
    """A V4 pool's state through its events (sorted (block, log, kind, data words))."""

    def __init__(self, token_is_0, sqrt_p, tick):
        self.token_is_0, self.sqrt_p, self.tick, self.liq = token_is_0, sqrt_p, tick, 0

    def apply(self, kind, w):
        if kind == "swap":
            self.sqrt_p, self.liq, self.tick = int(w[2], 16), int(w[3], 16), signed(w[4])
        else:  # modify: tickLower, tickUpper, liquidityDelta
            lo, hi, delta = signed(w[0]), signed(w[1]), signed(w[2])
            if lo <= self.tick < hi:
                self.liq = max(0, self.liq + delta)

    def token_reserve(self):
        return v4_token_reserve(self.liq, self.sqrt_p, self.token_is_0)


# --- download ---

def fetch(job):
    """Raw events of one coin: curve trades since its launch, V4 pools' Initialize / Swap / ModifyLiquidity."""
    import exit_truth as et
    from rhscanner.hooks import TOPIC_V4_INITIALIZE
    from rhscanner.live import TOPIC_MODIFY_LIQUIDITY
    token, curve, launch_block, first_block, hi = job
    try:
        out = {"curve": [], "pools": {}}
        if curve:
            lo = launch_block or first_block - 2_000_000
            for e in et.logs(lo, hi, [[et.CURVE_BUY, et.CURVE_SELL]], curve):
                out["curve"].append([int(e["blockNumber"], 16), int(e["logIndex"], 16),
                                     e["topics"][0] == et.CURVE_BUY, e["data"]])
        t = "0x" + "0" * 24 + token[2:].lower()
        inits = {}
        for topics in ([TOPIC_V4_INITIALIZE, None, t], [TOPIC_V4_INITIALIZE, None, None, t]):
            for a in range(max(0, first_block - 2_000_000), hi + 1, et.CHUNK):
                for e in et.logs(a, min(hi, a + et.CHUNK - 1), topics, et.PM):
                    inits[e["topics"][1]] = e
        for pid, e in inits.items():
            w = words(e["data"])  # fee, tickSpacing, hooks, sqrtPriceX96, tick
            born = int(e["blockNumber"], 16)
            evs = [[int(x["blockNumber"], 16), int(x["logIndex"], 16),
                    "swap" if x["topics"][0] == et.SWAP else "modify", x["data"]]
                   for x in et.logs(born, hi, [[et.SWAP, TOPIC_MODIFY_LIQUIDITY], pid], et.PM)]
            out["pools"][pid] = {"token_is_0": e["topics"][2][-40:] == token[2:].lower(), "born": born,
                                 "sqrt_p": int(w[3], 16), "tick": signed(w[4]), "fee": int(w[0], 16),
                                 "hooks": "0x" + w[2][-40:], "events": sorted(evs)}
        return token, out, None
    except Exception as exc:  # noqa: BLE001
        return token, None, str(exc)[:120]


def pool_fee(pid, born):
    """(lpFee, hooks) of a V4 pool from its Initialize (for cache lines written before the fee was kept)."""
    import exit_truth as et
    from rhscanner.hooks import TOPIC_V4_INITIALIZE
    for e in et.logs(born, born, [TOPIC_V4_INITIALIZE, pid], et.PM):
        w = words(e["data"])
        return int(w[0], 16), "0x" + w[2][-40:]
    return None, None


def fee_rates(raw, blk, n=FEE_N):
    """(b, s): the curve's fee + tax per eth of the last n buys / sells at or before blk (the coin's own setting;
    sells fall back to buys and back). Fee and tax are a share of the eth the trader pays (buy) or gets (sell)."""
    got = {True: [], False: []}
    for b, li, buy, data in sorted(raw, reverse=True):
        if b > blk:
            continue
        if len(got[buy]) < n:
            w = [int(x, 16) for x in words(data)]
            eth = w[0] if buy else w[1]
            if eth > 0:
                got[buy].append(sum(w[2:4]) / eth)
        if len(got[True]) >= n and len(got[False]) >= n:
            break
    b = float(np.median(got[True])) if got[True] else np.nan
    s = float(np.median(got[False])) if got[False] else np.nan
    return (b if b == b else s), (s if s == s else b)


def curve_trades(raw):
    """[(block, log, is_buy, eth, tokens)] from the raw curve events (CurveBuy: eth, tokens, fee, tax; CurveSell:
    tokens, eth, fee, tax). eth = what moved the curve's reserve: a buy's eth less fee and tax, a sell's eth plus them
    (checked on the chain 10 Nov: with that the k's of 6 coins agree to 0.0000-0.0011, with the raw eth 0.007-0.08)."""
    rows = []
    for b, li, buy, data in raw:
        w = [int(x, 16) for x in words(data)]
        cut = sum(w[2:4])
        eth, tok = (w[0] - cut, w[1]) if buy else (w[1] + cut, w[0])
        rows.append((b, li, buy, float(eth), float(tok)))
    return sorted(rows)


def depths(ev, blocks, usd_per_raw):
    """{moment: (venue, depth $)} at each block of `blocks` ({moment: block}); usd_per_raw {moment: $ per raw token}."""
    ct = curve_trades(ev["curve"])
    fit = fit_curve([r[2:] for r in ct]) if ct else None
    last_trade = [(r[0], r[1], "curve") for r in ct]
    pools = {pid: p for pid, p in ev["pools"].items()}
    for pid, p in pools.items():
        last_trade += [(b, li, pid) for b, li, kind, _ in p["events"] if kind == "swap"]
    last_trade.sort()
    res = {}
    for m, blk in blocks.items():
        if blk is None:
            continue
        upto = [x for x in last_trade if x[0] <= blk]
        venue = upto[-1][2] if upto else None
        x = None
        if venue == "curve" and fit:
            y0, k, _ = fit
            x = curve_token_reserve([r[2:] for r in ct], y0, k, sum(1 for r in ct if r[0] <= blk))
        elif venue in pools:
            p = pools[venue]
            st = Pool(p["token_is_0"], p["sqrt_p"], p["tick"])
            for b, li, kind, data in p["events"]:
                if b > blk:
                    break
                st.apply(kind, words(data))
            x = st.token_reserve()
        d = x * usd_per_raw[m] if x is not None and usd_per_raw.get(m) else np.nan
        if venue == "curve" and fit and fit[2] > BAD_FIT:
            d = np.nan
        if venue == "curve":
            rates = fee_rates(ev["curve"], blk)
        elif venue in pools and pools[venue].get("fee") is not None and not pools[venue]["fee"] & DYNAMIC_FEE:
            rates = (pools[venue]["fee"] / 1e6,) * 2
        else:
            rates = (np.nan, np.nan)
        res[m] = (venue, d) + rates
    return res, fit


def main():
    flags = {"--top", "--delay"}
    args = [a for i, a in enumerate(sys.argv[1:]) if not a.startswith("--") and sys.argv[i] not in flags]
    top, delay = arg("--top", 0.05), arg("--delay", 10)
    db = sqlite3.connect(args[0])
    picks = pd.read_parquet(args[1]).sort_values("ts")
    picks["coin"] = picks.coin.str.lower()
    picks = picks[picks.pct >= 1 - top]
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}
    launches = {t: (c, b) for t, c, b in db.execute("SELECT lower(token), lower(curve), block FROM launches")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    picks = picks[picks.ts + HOLD + LATER < data_end]
    info = {}
    for r in picks.itertuples():
        tr = np.array(db.execute("SELECT ts, block, side, usd, amount FROM trades WHERE token=? ORDER BY ts",
                                 (names[r.coin],)).fetchall(), float)
        p = path_of(tr, r.ts, delay)
        ok = (tr[:, 3] > 0) & (tr[:, 4] > 0)
        def usd_at(b):
            m = ok & (tr[:, 1] <= b)
            return float(tr[m, 3][-1] / tr[m, 4][-1]) if m.any() else np.nan
        blocks = {"buy": p["ab"] + int(delay * scorecard.BPS)}
        if p["t5"] is not None:
            blocks.update({"5x": p["hb"], "later": p["hb"] + int(LATER * scorecard.BPS)})
            usd = {"buy": usd_at(blocks["buy"]), "5x": 5 * usd_at(p["ab"]), "later": usd_at(blocks["later"])}
        else:
            blocks["exit"] = p["eb"]
            usd = {"buy": usd_at(blocks["buy"]), "exit": usd_at(p["eb"])}
        info[r.Index] = (r.coin, r.ts, blocks, usd, int(tr[0, 1]))
    out_path = Path(args[2])
    cache = out_path.with_suffix(".cache.jsonl")
    ev = {}
    if cache.exists():
        for line in cache.read_text().splitlines():
            t, e = json.loads(line)
            ev[t] = e
    need = int((HOLD + LATER + 300) * scorecard.BPS)
    todo = {}
    for coin, ts, blocks, usd, first in info.values():
        if coin not in ev:
            curve, lb = launches.get(coin, (None, None))
            todo[coin] = (coin, curve, lb, first, max(b for b in blocks.values()) + need // 10)
    print(f"{len(info)} seçim · {len(ev)} coin önbellekte · {len(todo)} indirilecek", flush=True)
    if "--probe" in sys.argv:
        for job in list(todo.values())[:5]:
            if job[1]:
                _, e, err = fetch(job)
                for b, li, buy, data in (e or {"curve": []})["curve"][:3]:
                    print("curve", "buy" if buy else "sell", b, len(words(data)), "word:", words(data))
                print("err", err) if err else None
        return
    t0, failed = time.time(), 0
    with ThreadPoolExecutor(3) as pool, open(cache, "a") as f:
        for n, done in enumerate(as_completed([pool.submit(fetch, j) for j in todo.values()])):
            token, e, err = done.result()
            if e is None:
                failed += 1
                print("  hata", token, err, flush=True)
                continue
            ev[token] = e
            f.write(json.dumps([token, e]) + "\n")
            f.flush()
            if n % 20 == 0:
                print(f"  {n}/{len(todo)} · {time.time() - t0:.0f} sn · hata {failed}", flush=True)
    fees_path = out_path.with_suffix(".fees.json")
    fees = json.loads(fees_path.read_text()) if fees_path.exists() else {}
    miss = [(c, pid, p["born"]) for c, e in ev.items() if c in {i[0] for i in info.values()}
            for pid, p in e["pools"].items() if "fee" not in p and pid not in fees]
    if miss:
        print(f"havuz ücreti: {len(miss)} havuz", flush=True)
        with ThreadPoolExecutor(3) as pool:
            for (c, pid, _), fh in zip(miss, pool.map(lambda j: pool_fee(j[1], j[2]), miss)):
                fees[pid] = fh
        fees_path.write_text(json.dumps(fees))
    for e in ev.values():
        for pid, p in e["pools"].items():
            if "fee" not in p and pid in fees:
                p["fee"], p["hooks"] = fees[pid]
    rows = []
    for coin, ts, blocks, usd, _ in info.values():
        row = {"coin": coin, "ts": ts}
        if coin in ev:
            res, fit = depths(ev[coin], blocks, usd)
            for m, (venue, d, b, s) in res.items():
                row[f"venue_{m}"], row[f"depth_{m}"], row[f"fb_{m}"], row[f"fs_{m}"] = venue, d, b, s
            if fit:
                row["y0"], row["fit_spread"] = fit[0], fit[2]
        rows.append(row)
    out = pd.DataFrame(rows)
    for m in MOMENTS:
        for c in (f"venue_{m}", f"depth_{m}", f"fb_{m}", f"fs_{m}"):
            if c not in out:
                out[c] = None if c.startswith("venue") else np.nan
    out.to_parquet(out_path, index=False)
    est = picks.set_index("coin").depth_usd if "depth_usd" in picks else None
    print(f"\nbitti: {len(out)} seçim, zincir verisi alınamayan {failed}")
    for m in MOMENTS:
        d = out[f"depth_{m}"].dropna()
        if len(d):
            v = out[f"venue_{m}"].dropna()
            print(f"  {m:5s}: {len(d)} seçim · derinlik medyan ${d.median():,.0f} (çeyrek ${d.quantile(.25):,.0f}–"
                  f"${d.quantile(.75):,.0f}) · curve %{100 * (v == 'curve').mean():.0f}")
    if est is not None:
        both = out.dropna(subset=["depth_buy"]).copy()
        both["est"] = both.coin.map(est.groupby(level=0).first())
        both = both.dropna(subset=["est"])
        r = both.depth_buy / both.est
        print(f"  gerçek / tahmin (alış): medyan {r.median():.2f}, çeyrek {r.quantile(.25):.2f}–{r.quantile(.75):.2f}"
              f" ({len(both)} seçim)")
    if "fit_spread" in out:
        print(f"  curve uyumu (fit_spread medyanı, ~0 = sabit çarpım): {out.fit_spread.median():.4f}; "
              f"y0 medyanı {out.y0.median():.4g}")


if __name__ == "__main__":
    main()
