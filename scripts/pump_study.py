"""pump.fun moments (PROJE.md §0 A8, step 6): what new coins look like at their k-th distinct Fomo buyer, and what
happened next. The pump.fun twin of scripts/winner_study.py, same measurement rules (PROJE.md §6).

  python scripts/pump_study.py <solana.db from scripts/solana_import.py> <out.parquet>

Coins: first Fomo trade on the bonding curve (before graduation) at least an hour after the data starts (so "new
on Fomo" is known then, not later). Moment: the k-th distinct Fomo buyer (k = 3, 5, 10). Only what is known at the
moment is used. Price = USD per raw token of a trade (SOL amount / token amount x SOL/USD of the hour); the alert price
is the moment's own buy (rule 2). Outcome from every later Fomo trade, curve and PumpSwap alike:
- t2x_h: hours until two buys in a row at >= 2x the alert price (rule 4; NaN if never), obs_h: hours of data after
- peak (two-buy held high, capped 100x), trap_1h: the price fell to <= 10 % of the alert price within 1 h with no 2x
  first (a dump / rug; the curve itself cannot block sells), graduated: the curve emptied or the coin was seen on
  PumpSwap afterwards
Features: speed and size of Fomo buying (as Robinhood), sellers, runup, market cap, the coin's real age (created_ts
from the collector), curve progress (share of the 793.1M sellable tokens already bought), the creator's earlier coins
seen on Fomo, buys in the same slot (bots), small buys, the last 60 s.
"""

import sqlite3
import sys

import numpy as np
import pandas as pd

KS = (3, 5, 10)
CURVE_TOKENS = 793_100_000 * 10**6  # real tokens on a fresh pump.fun curve (raw, 6 decimals)
SUPPLY = 10**9 * 10**6  # every pump.fun coin: 1B tokens, 6 decimals
CAP = 100.0


def two_in_row(mask: np.ndarray) -> int | None:
    hit = np.flatnonzero(mask[1:] & mask[:-1])
    return int(hit[0]) + 1 if len(hit) else None


def main():
    db = sqlite3.connect(sys.argv[1])
    t = pd.read_sql("SELECT ts, slot, venue, mint, side, user, lamports, tokens, rtok FROM trades WHERE tokens > 0 "
                    "AND lamports > 0 ORDER BY ts, slot", db)
    sol = pd.read_sql("SELECT ts, usd FROM sol_price ORDER BY ts", db)
    t["sol_usd"] = np.interp(t.ts, sol.ts, sol.usd)
    t["usd"] = t.lamports / 1e9 * t.sol_usd
    t["px"] = t.usd / t.tokens
    mints = pd.read_sql("SELECT mint, creator, created_ts, older_than FROM mints", db).set_index("mint")
    data_end = t.ts.max()
    start = t.ts.min() + 3600
    first_curve = t[t.venue == 1].groupby("mint").ts.min()
    first_any = t.groupby("mint").ts.min()
    coins = first_curve[(first_curve >= start) & (first_curve == first_any.reindex(first_curve.index))].index
    creator_first = {}  # creator -> times of their earlier coins' first Fomo trade (known history only)
    for mint, ts in first_any.sort_values().items():
        c = mints.creator.get(mint)
        if isinstance(c, str):
            creator_first.setdefault(c, []).append(ts)
    rows = []
    for mint, g in t[t.mint.isin(coins)].groupby("mint", sort=False):
        ts, side, user, usd, px = g.ts.values, g.side.values, g.user.values, g.usd.values, g.px.values
        venue, slot, rtok = g.venue.values, g.slot.values, g.rtok.values
        buyers = []
        for i in range(len(g)):
            if side[i] == 1 and user[i] not in buyers:
                buyers.append(user[i])
                k = len(buyers)
                if k not in KS:
                    continue
                t0, p0 = ts[i], px[i]
                past = slice(0, i + 1)
                b = side[past] == 1
                bu = usd[past][b]
                sellers = set(user[past][~b])
                after = slice(i + 1, None)
                apx, aside, ats = np.minimum(px[after], CAP * p0), side[after], ts[after]
                bmask = aside == 1
                j = two_in_row(apx[bmask] >= 2 * p0)
                t2x = (ats[bmask][j] - t0) / 3600 if j is not None else np.nan
                held = np.minimum(apx[bmask][1:], apx[bmask][:-1]) if bmask.sum() > 1 else np.array([p0])
                low_1h = apx[ats <= t0 + 3600]
                trap = bool(len(low_1h) and (low_1h <= 0.1 * p0).any() and not (t2x <= 1))
                if trap and not np.isnan(t2x):  # the dump came before the 2x?
                    first_low = ats[np.flatnonzero((apx <= 0.1 * p0) & (ats <= t0 + 3600))[0]]
                    trap = first_low < t0 + 3600 * t2x
                created = mints.created_ts.get(mint)
                prev = [x for x in creator_first.get(mints.creator.get(mint), []) if x < ts[0]]
                last_rtok = rtok[past][~np.isnan(rtok[past])]
                rows.append({
                    "coin": mint, "k": k, "ts": t0, "p0": p0,
                    "t2x_h": t2x, "obs_h": (data_end - t0) / 3600, "peak": held.max() / p0 if len(held) else 1.0,
                    "trap_1h": trap, "graduated": bool((venue[after] == 2).any() or (rtok[after] == 0).any()),
                    "mins_to_k": (t0 - ts[0]) / 60, "trades_to_k": i + 1,
                    "usd_all": bu.sum(), "usd_per_trade": bu.mean(), "max_buy": bu.max(),
                    "sellers": len(sellers), "early_sold": sum(w in sellers for w in buyers[:k]) / k,
                    "sell_usd_share": usd[past][~b].sum() / max(1.0, usd[past].sum()),
                    "buyers_5m": len(set(user[past][b & (ts[past] > t0 - 300)])),
                    "usd_10m": usd[past][b & (ts[past] > t0 - 600)].sum(),
                    "buyers_60s": len(set(user[past][b & (ts[past] > t0 - 60)])),
                    "usd_60s_share": usd[past][b & (ts[past] > t0 - 60)].sum() / max(1.0, bu.sum()),
                    "runup": p0 / px[past][b][0],
                    "mcap": p0 * SUPPLY,
                    "age_min": (t0 - created) / 60 if created == created and created else np.nan,
                    "old_coin": bool(mints.older_than.get(mint) == mints.older_than.get(mint)
                                     and mints.older_than.get(mint) not in (None, -1)),
                    "curve_pct": 100 * (1 - last_rtok[-1] / CURVE_TOKENS) if len(last_rtok) else np.nan,
                    "same_slot_buys": int(pd.Series(slot[past][b]).duplicated(keep=False).sum()),
                    "small_buy_share": float((bu < 20).mean()),
                    "creator_prev": len(prev),
                })
                if k == KS[-1]:
                    break
    out = pd.DataFrame(rows)
    out.to_parquet(sys.argv[2], index=False)
    print(f"{len(coins)} yeni coin, {len(out)} an ({out.groupby('k').size().to_dict()})")


if __name__ == "__main__":
    main()
