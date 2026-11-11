"""BNB picks' real pool depth, venue fees / tax and exit prices from the backfill (scripts/bnb_backfill.py, veri
arastirma/bnb-geri/), in the formats scripts/scorecard.py reads (PROJE.md §4.17):

  python scripts/bnb_depth.py <bnb-geri folder> <bnb trades.db> <out folder>
  -> <out>/events.jsonl (--events), <out>/depth.parquet (--depth and --fees), coverage printed

Venues, decoded from the receipts' raw logs (layouts checked on the data, 11 Nov):
- flap.sh bonding curve (portal 0xe2ce6ab8...): the portal trades through a V2-style pair per coin (Swap with
  sender = the portal, Sync = the curve's virtual reserves of quote and coin; prices match Fomo's within ~1 %); the
  quote is the token moving to / from the portal (WBNB or a base token). The portal's own events 0x115c78ad (sold) /
  0x4c35e20d (reserve) were ~14x off Fomo's prices (11 Nov) and are not used; fee event 0xb4aa5d6b
- PancakeSwap V3 Swap 0x19b47279 (amount0, amount1, sqrtPriceX96, liquidity, tick, protocol fees): quote side of the
  active range = L * sqrtP (coin = token0) or L / sqrtP
- PancakeSwap V2 Sync 0x1c411e9a: reserves
A pool's tokens come from the Transfers to / from it in the same transaction; $ per token: USDT / USDC / BUSD / USD1
(18 decimals) = 1, WBNB = the BNB price from the USDT-WBNB V3 pool 0x172fcd41 swaps (nearest block), any other quote
(a base token the route passes through) from the transaction's own pools that link it to a priced token. Uniswap V4
pools (one PoolManager for all) are not decoded.
Per sampled transaction (alert, 5x, 5x + 10 min, last before 3 h, every 5 min): the coin's deepest venue in it →
$ price per raw token and $ depth. Events: one pseudo-venue "usd" (a coin moving from the curve to its pool after
graduation is valued there, not at 0) plus a "pull" when the depth falls to PULL_SHARE of its peak since the alert.
Fees per moment (fb_ / fs_): venue fee (curve: measured fee / Fomo $; V3 / V2: V3_FEE / V2_FEE assumed, the tier is not
in the event) + the coin's transfer tax (measured: 1 - coin reaching Fomo's executor / coin leaving the venue, median).
"""

import gzip
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

Q96 = 2 ** 96
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
V3_SWAP = "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83"
V2_SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
V2_SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"
FLAP_FEE = "0xb4aa5d6b2390b2b8892ff84cb0ef9a64e969e1af22d049fa61cc2cf66c6ab7bd"
FLAP_PORTAL = "0xe2ce6ab80874fa9fa2aae65d277dd6b8e65c9de0"
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
USD = {"0x55d398326f99059ff775485246999027b3197955", "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",
       "0xe9e7cea3dedca5984780bafc599bd69add087d56", "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d"}
BNB_POOL = "0x172fcd41e0913e95784454622d1c3724f546f849"  # PancakeSwap V3 USDT (token0) / WBNB (token1)
EXECUTORS = {"0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f", "0x0729e2a4716d9f7dd17858d5d504426d228697f7"}
V3_FEE, V2_FEE = 0.01, 0.0025
PULL_SHARE = 0.2


def words(data):
    return [int(data[2 + 64 * i: 2 + 64 * (i + 1)], 16) for i in range((len(data) - 2) // 64)]


def signed(w):
    return w - (1 << 256) if w >> 255 else w


def load(folder):
    txs = defaultdict(list)
    for f in sorted(Path(folder).glob("venue_logs_*.jsonl.gz")):
        for line in gzip.open(f, "rt"):
            coin, b, tx, li, addr, topics, data = json.loads(line)
            txs[(coin, tx)].append((b, li, addr, topics.split(","), data))
    xfer = []
    for f in sorted(Path(folder).glob("coin_xfer_*.jsonl.gz")):
        for line in gzip.open(f, "rt"):
            coin, b, tx, li, src, dst, amount = json.loads(line)
            xfer.append((coin, b, tx, src, dst, float(amount)))
    return txs, pd.DataFrame(xfer, columns=["coin", "block", "tx", "src", "dst", "amount"])


def bnb_prices(txs):
    out = []
    for L in txs.values():
        for b, li, addr, t, data in L:
            if addr == BNB_POOL and t[0] == V3_SWAP:
                sp = words(data)[2] / Q96
                out.append((b, 1 / sp ** 2))  # USDT per WBNB (both 18 decimals)
    out = sorted(set(out))
    return np.array([x[0] for x in out]), np.array([x[1] for x in out])


def tx_state(coin, L, bnb, known=None):
    """The transaction's priceable pools and $ prices: (edges, usd, flap fee). edges: (pool, kind, token0, token1,
    price token1 per token0 raw, depth in token1 raw, depth in token0 raw); usd: $ per raw unit of each token priced
    (USD stables, WBNB from the BNB price, `known` [token -> $ near this block] for the rest, then through the pools).
    The flap.sh portal trades a coin on its curve through a V2-style pair that emits Swap (sender = the portal) and
    Sync with the curve's real virtual reserves (quote, coin); its tokens are the coin and the quote token moving to /
    from the portal."""
    pools = defaultdict(set)  # pool -> tokens moving to / from it
    portal_quote, portal_pairs = set(), set()
    for b, li, addr, t, data in L:
        if t[0] == TRANSFER and len(t) >= 3:
            for side in (t[1], t[2]):
                pools["0x" + side[-40:]].add(addr)
            if addr != coin and FLAP_PORTAL[2:] in (t[1][-40:], t[2][-40:]):
                portal_quote.add(addr)
    for b, li, addr, t, data in L:
        if t[0] == V2_SWAP and len(t) > 1 and t[1][-40:] == FLAP_PORTAL[2:] and len(portal_quote) == 1:
            pools[addr] = {coin} | portal_quote
            portal_pairs.add(addr)
    edges, fee = [], None
    for b, li, addr, t, data in L:
        if addr == FLAP_PORTAL and t[0] == FLAP_FEE and len(t) > 1 and "0x" + t[1][-40:] == coin:
            fee = words(data)[0] / 1e18
        elif t[0] in (V3_SWAP, V2_SYNC) and len(pools.get(addr, ())) == 2:
            t0, t1 = sorted(pools[addr])
            w = words(data)
            if t[0] == V3_SWAP:
                sp, liq = w[2] / Q96, w[3]
                if sp and liq:
                    edges.append((addr, "v3", t0, t1, sp ** 2, liq * sp, liq / sp))
            elif w[0] and w[1]:
                kind = "curve" if addr in portal_pairs else "v2"
                edges.append((addr, kind, t0, t1, w[1] / w[0], w[1], w[0]))
    usd = {q: 1e-18 for q in USD}  # $ per raw unit (18 decimals)
    if bnb:
        usd[WBNB] = bnb / 1e18
    for _ in range(4):  # $ prices through the route's pools (USDT -> WBNB -> a base token -> the coin)
        for addr, kind, t0, t1, p10, d1, d0 in edges:
            if t0 in usd and t1 not in usd and t1 != coin:
                usd[t1] = usd[t0] / p10
            elif t1 in usd and t0 not in usd and t0 != coin:
                usd[t0] = usd[t1] * p10
        for q, v in (known or {}).items():
            usd.setdefault(q, v)
    return edges, usd, fee


def sample(coin, L, bnb, known=None):
    """(block, $ per raw token, $ depth, venue kind, venue address, curve fee or NaN) of the coin's deepest venue in
    one transaction, or None."""
    b0 = L[0][0]
    edges, usd, fee = tx_state(coin, L, bnb, known)
    found = []
    for addr, kind, t0, t1, p10, d1, d0 in edges:
        f = fee if kind == "curve" and fee is not None else np.nan
        if coin == t0 and t1 in usd:
            found.append((b0, p10 * usd[t1], d1 * usd[t1], kind, addr, f))
        elif coin == t1 and t0 in usd:
            found.append((b0, usd[t0] / p10, d0 * usd[t0], kind, addr, f))
    return max(found, key=lambda x: x[2]) if found else None


def quote_prices(txs, bb, bp):
    """token -> (blocks, $ per raw unit) from every transaction that prices it through its own pools (for a quote
    token a coin's transaction cannot price, e.g. one routed through Uniswap V4)."""
    pts = defaultdict(list)
    for (coin, tx), L in txs.items():
        b = L[0][0]
        bnb = float(bp[np.searchsorted(bb, b).clip(0, len(bb) - 1)]) if len(bb) else None
        for q, v in tx_state(coin, L, bnb)[1].items():
            if q not in USD and q != WBNB and q != coin:
                pts[q].append((b, v))
    return {q: (np.array([x[0] for x in sorted(v)]), np.array([x[1] for x in sorted(v)])) for q, v in pts.items()}


def known_at(table, b):
    out = {}
    for q, (blocks, vals) in table.items():
        i = int(np.searchsorted(blocks, b).clip(0, len(blocks) - 1))
        j = min((k for k in (i - 1, i) if 0 <= k < len(blocks)), key=lambda k: abs(blocks[k] - b))
        if abs(blocks[j] - b) <= 2000:  # ~15 min
            out[q] = float(vals[j])
    return out


def coin_tax(xf, venues):
    """Median transfer tax of the coin's Fomo buys: 1 - coin reaching an executor / coin leaving the venue(s)."""
    out = []
    for tx, g in xf.groupby("tx"):
        left = g[g.src.isin(venues)].amount.sum()
        got = g[g.dst.isin(EXECUTORS)].amount.sum()
        if left > 0 and got > 0:
            out.append(max(0.0, 1 - got / left))
    return float(np.median(out)) if out else np.nan


def main():
    folder, db_path, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    txs, xfer = load(folder)
    bb, bp = bnb_prices(txs)
    qt = quote_prices(txs, bb, bp)
    jobs = pd.read_csv(folder / "jobs.csv")
    db = sqlite3.connect(db_path)
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}
    by_coin = defaultdict(list)
    for (coin, tx), L in txs.items():
        by_coin[coin].append(sorted(L, key=lambda x: x[1]))
    xf_coin = {c: g for c, g in xfer.groupby("coin")}
    ev_out, rows = open(out / "events.jsonl", "w"), []
    fomo_usd = {}
    for r in jobs.itertuples():
        S = []
        for L in sorted(by_coin.get(r.coin, []), key=lambda L: L[0][0]):
            b = L[0][0]
            bnb = float(bp[np.searchsorted(bb, b).clip(0, len(bb) - 1)]) if len(bb) else None
            s = sample(r.coin, L, bnb, known_at(qt, b))
            if s:
                S.append(s)
        ev, peak = [], 0.0
        pulled = False
        for b, px, dep, kind, addr, fee in S:
            if b < r.alert_block:
                continue
            ev.append([b, 0, "usd", px, "trade"])
            peak = max(peak, dep)
            if not pulled and peak > 0 and dep <= PULL_SHARE * peak:
                ev.append([b, 10 ** 9, "usd", 0.0, "pull"])
                pulled = True
        ev_out.write(json.dumps([r.coin, ev]) + "\n")
        venues = {s[4] for s in S}
        tax = coin_tax(xf_coin[r.coin], venues) if r.coin in xf_coin else np.nan
        # curve fee share: fee (BNB) x BNB price / the Fomo $ of that transaction is not joined here; the curve's fee
        # is read as fee / (quote moved), estimated from consecutive samples' reserve change when available
        row = {"coin": r.coin, "ts": r.ts}

        def at(block, before=True):
            c = [s for s in S if (s[0] <= block if before else s[0] >= block)]
            return (c[-1] if before else c[0]) if c else None

        hb = r.hit_block if r.hit_block > 0 else None
        moments = {"buy": at(r.alert_block + 22, False), "exit": at(r.end_block)}
        if hb:
            moments.update({"5x": at(hb, False), "later": at(hb + 1332, False)})
        for m in ("buy", "5x", "later", "exit"):
            s = moments.get(m)
            row[f"depth_{m}"] = s[2] if s else np.nan
            kind = s[3] if s else None
            row[f"venue_{m}"] = None if s is None else ("curve" if kind == "curve" else kind)
            vf = (0.01 if kind == "curve" else V3_FEE if kind == "v3" else V2_FEE if kind == "v2" else np.nan)
            row[f"fb_{m}"] = row[f"fs_{m}"] = vf + (tax if np.isfinite(tax) else 0.0) if s else np.nan
        row["tax"], row["samples"] = tax, len(S)
        rows.append(row)
    ev_out.close()
    d = pd.DataFrame(rows)
    d.to_parquet(out / "depth.parquet")
    print(f"{len(d)} seçim · örnek medyanı {d.samples.median():.0f} · ölçülen derinlik: alış %{100 * d.depth_buy.notna().mean():.0f}, "
          f"çıkış %{100 * d.depth_exit.notna().mean():.0f}, 5x olanlarda %{100 * d['depth_5x'].notna().sum() / max(1, (jobs.hit_block > 0).sum()):.0f}")
    print("alıştaki mekan:", d.venue_buy.value_counts(dropna=False).to_dict(), "· vergi medyanı", round(float(d.tax.median()), 4))


if __name__ == "__main__":
    main()
