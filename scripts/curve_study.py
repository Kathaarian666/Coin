"""Earlier than Fomo: the k-th on-chain buyer of a Pons coin's bonding curve (scripts/curve_download.py data).

  python scripts/curve_study.py <trades.db> <out.parquet>

Price series per coin, USD per token: curve trades (ETH per token x ETH/USD) plus Fomo buys. ETH/USD is read
from the data: Fomo buys matched with curve buys of the same coin within 20 blocks. Checkpoints: the moment the
k-th distinct curve buyer arrives (KS). Features use only the curve trades up to then; the label is the highest
price held for two trades in a row in the next 72 h over the price at the checkpoint (median of the last 3).
"""

import sqlite3
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

KS = (5, 10, 20, 40)
HORIZON_BLOCKS = 72 * 36000
SNIPE_BLOCKS = 30


def main():
    db = sqlite3.connect(sys.argv[1])
    t0 = time.time()
    curve = pd.read_sql("SELECT token, block, li, side, trader, eth, tokens FROM curve_trades ORDER BY token, block, li", db)
    launches = {t: (b, lc.lower()) for t, b, lc in db.execute("SELECT lower(token), block, launcher FROM launches")}
    launcher_blocks = defaultdict(list)
    for b, lc in launches.values():
        launcher_blocks[lc].append(b)
    for v in launcher_blocks.values():
        v.sort()
    tokens = set(curve.token)
    ids = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    fomo = pd.read_sql(f"SELECT token, block, ts, usd, amount FROM trades WHERE side = 1 AND usd > 0 AND amount > 0 "
                       f"AND token IN ({','.join(str(ids[t]) for t in tokens if t in ids)})", db)
    rev = {v: k for k, v in ids.items()}
    fomo["token"] = fomo.token.map(rev)
    fomo["px"] = fomo.usd / fomo.amount * 1e18  # USD per whole token
    sample = np.array(db.execute("SELECT block, ts FROM trades WHERE rowid % 500 = 0 ORDER BY block").fetchall(), float)
    print(f"{len(curve):,} curve işlemi, {len(fomo):,} Fomo alımı ({time.time() - t0:.0f} sn)", flush=True)

    # ETH/USD from Fomo buys landing next to a curve buy of the same coin
    cb = curve[(curve.side == 1) & (curve.tokens > 0)].assign(eth_px=lambda d: d.eth / d.tokens)
    ratios = []
    for tok, f in fomo.groupby("token"):
        c = cb[cb.token == tok]
        if c.empty:
            continue
        idx = np.searchsorted(c.block.values, f.block.values)
        for j, (blk, px) in zip(idx, zip(f.block.values, f.px.values)):
            for k in (j - 1, j):
                if 0 <= k < len(c) and abs(c.block.values[k] - blk) <= 20:
                    ratios.append((blk, px / c.eth_px.values[k]))
                    break
    r = pd.DataFrame(ratios, columns=["block", "ratio"])
    r = r[(r.ratio > 500) & (r.ratio < 20000)]
    day = (r.block // 864000)
    eth_usd_by_day = r.groupby(day).ratio.median()
    print(f"ETH/USD eşleşme {len(r):,}: medyan ${r.ratio.median():,.0f} (günlük {eth_usd_by_day.min():,.0f}–"
          f"{eth_usd_by_day.max():,.0f})", flush=True)

    def eth_usd(block):
        return float(eth_usd_by_day.get(block // 864000, r.ratio.median()))

    rows = []
    for n, (tok, c) in enumerate(curve.groupby("token", sort=False)):
        lb, launcher = launches[tok]
        blk, side, who = c.block.values, c.side.values, c.trader.str.lower().values
        eth, toks = c.eth.values, c.tokens.values
        cpx = np.where(toks > 0, eth / np.where(toks > 0, toks, 1), np.nan) * eth_usd(int(lb))
        f = fomo[fomo.token == tok]
        series = pd.concat([pd.DataFrame({"block": blk[side == 1], "px": cpx[side == 1]}),
                            pd.DataFrame({"block": f.block.values, "px": f.px.values})]).dropna()
        series = series.sort_values("block", kind="stable")
        s_blk, s_px = series.block.values, series.px.values
        if len(s_px) < 5:
            continue
        held = np.minimum(s_px[:-1], s_px[1:])
        buyers, order = set(), []
        for i in range(len(c)):
            if side[i] == 1 and who[i] not in buyers:
                buyers.add(who[i])
                order.append(i)
        for k in KS:
            if len(order) < k:
                break
            i = order[k - 1]
            b = blk[i]
            ns = np.searchsorted(s_blk, b, side="right")
            end = np.searchsorted(s_blk, b + HORIZON_BLOCKS, side="right")
            if ns < 2 or end - 1 <= ns:
                continue
            p_now = float(np.median(s_px[max(0, ns - 3):ns]))
            past = slice(0, i + 1)
            pb = side[past] == 1
            b_eth, b_who = eth[past][pb], who[past][pb]
            per = pd.Series(b_eth).groupby(b_who).sum()
            sellers = set(who[past][~pb])
            recent = blk[past] > b - 600
            prev = (blk[past] <= b - 600) & (blk[past] > b - 1200)
            rows.append({
                "coin": tok, "k": k, "block": int(b), "ts": float(np.interp(b, sample[:, 0], sample[:, 1])),
                "peak": float(held[ns:end - 1].max() / p_now),
                "mins_from_launch": (b - lb) / 600,
                "buys": int(pb.sum()),
                "eth_all": float(b_eth.sum()),
                "eth_per_buy": float(b_eth.mean()),
                "max_buy_eth": float(b_eth.max()),
                "top_buyer_share": float(per.max() / per.sum()) if per.sum() > 0 else 1.0,
                "repeat_buys": float(1 - len(set(b_who)) / len(b_who)),
                "sellers": len(sellers),
                "sell_eth_share": float(eth[past][~pb].sum() / max(1e-12, eth[past].sum())),
                "buyers_1m": len(set(who[past][recent & (side[past] == 1)])),
                "buyers_prev1m": len(set(who[past][prev & (side[past] == 1)])),
                "snipe_share": float(b_eth[blk[past][pb] <= lb + SNIPE_BLOCKS].sum() / max(1e-12, b_eth.sum())),
                "dev_bought": float(per.get(launcher, 0.0) / max(1e-12, per.sum())),
                "dev_sold": launcher in sellers,
                "curve_sold_pct": float((toks[past][pb].sum() - toks[past][~pb].sum()) / 1e9 * 100),
                "runup": float(p_now / s_px[0]),
                "mcap_usd": p_now * 1e9,
                "fomo_buys_before": int((f.block.values <= b).sum()),
                "launcher_prior": int(np.searchsorted(launcher_blocks[launcher], lb)),
            })
        if n % 500 == 0:
            print(f"{n}/{curve.token.nunique()} coin · {len(rows)} kontrol noktası · {time.time() - t0:.0f} sn", flush=True)
    pd.DataFrame(rows).to_parquet(sys.argv[2])
    print(f"bitti: {len(rows)} kontrol noktası ({time.time() - t0:.0f} sn)", flush=True)


if __name__ == "__main__":
    main()
