"""What do coins that later rose 5x / 10x look like at the moment they became noticeable? (No costs yet.)

  python scripts/winner_study.py <trades.db> <out.parquet> [<first trade from> <until>]

Checkpoints: the moment a coin's k-th distinct Fomo buyer arrives (k in KS). At each checkpoint only what was
known then is used; the label is the highest price held for two buys in a row in the next 72 h, as a multiple
of the checkpoint price (the last buy price). The 2x label of the plan (PROJE.md §1, no time limit):
`t2x_h` = hours until two buys in a row at >= 2x the checkpoint price (NaN if never), `obs_h` = hours of data
after the checkpoint. Coins first traded 17 Sep 18:41 - 28 Sep (72 h fit).
Features follow the signals the public research and scanners use: speed of money and buyers, trade sizes and
the largest buy, buyer diversity, early holders still holding, fresh wallets, smart wallets, runup, FDV,
Pons launch age and the launcher's history.
"""

import bisect
import sqlite3
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

KS = (3, 5, 10, 20)
HORIZON = 72 * 3600
START = pd.Timestamp("2026-09-17 18:41").value / 1e9
END = pd.Timestamp("2026-09-28 15:00").value / 1e9
WIN = 10.0  # a "winner" wallet trade: its first buy in a coin that later held 10x


class Sparse:
    """O(1) range min / max and 'first index from j with value >= x' over a fixed array."""

    def __init__(self, values: np.ndarray, op):
        self.op, self.levels = op, [values]
        k = 1
        while 2 * k <= len(values):
            prev = self.levels[-1]
            self.levels.append(op(prev[:-k], prev[k:]))
            k *= 2

    def query(self, lo: int, hi: int) -> float:  # inclusive
        lvl = (hi - lo + 1).bit_length() - 1
        t = self.levels[lvl]
        return self.op(t[lo], t[hi - (1 << lvl) + 1])

    def first_at_least(self, lo: int, x: float) -> int:
        """First index >= lo whose value >= x (max table only); len if none."""
        n, pos = len(self.levels[0]), lo
        for lvl in range(len(self.levels) - 1, -1, -1):
            if pos + (1 << lvl) <= n and self.levels[lvl][pos] < x:
                pos += 1 << lvl
        return pos


def main():
    global START, END
    db_path, out = sys.argv[1], sys.argv[2]
    if len(sys.argv) > 4:  # a different window of first Fomo trades, e.g. fresh days
        START, END = pd.Timestamp(sys.argv[3]).value / 1e9, pd.Timestamp(sys.argv[4]).value / 1e9
    t0 = time.time()
    db = sqlite3.connect(db_path)
    names = {i: a.lower() for i, a in db.execute("SELECT id, addr FROM names")}
    supply = {a.lower(): r for a, r in db.execute("SELECT addr, raw FROM supply") if r}
    launches = {tok: (ts, launcher) for tok, ts, launcher in db.execute("SELECT lower(token), ts, lower(launcher) FROM launches")}
    launcher_times = defaultdict(list)
    for ts, launcher in launches.values():
        launcher_times[launcher].append(ts)
    for v in launcher_times.values():
        v.sort()
    tr = pd.read_sql("SELECT ts, token, side, trader, usd, amount FROM trades ORDER BY token, ts", db)
    print(f"{len(tr):,} işlem ({time.time() - t0:.0f} sn)", flush=True)
    data_end = tr.ts.max()

    # wallet facts known over time: first ever Fomo trade; early buys in coins that later held 10x
    first_seen = tr.groupby("trader").ts.min().to_dict()
    coins = {tok: g for tok, g in tr.groupby("token", sort=False)}
    smart_known = defaultdict(list)  # wallet -> times its 10x picks became known
    for tok, g in coins.items():
        b = g[(g.side == 1) & (g.usd > 0) & (g.amount > 0)]
        if len(b) < 5:
            continue
        px = (b.usd / b.amount).values
        held = np.minimum(px[:-1], px[1:])
        tab = Sparse(held, np.maximum)
        ts = b.ts.values
        seen = set()
        for i, w in enumerate(b.trader.values[:-2]):
            if w in seen:
                continue
            seen.add(w)
            k = tab.first_at_least(i + 1, WIN * px[i])
            if k < len(held):
                smart_known[w].append(ts[k + 1])
    for v in smart_known.values():
        v.sort()
    print(f"cüzdan geçmişi: {len(smart_known):,} cüzdanın en az bir 10x erken alımı ({time.time() - t0:.0f} sn)", flush=True)

    rows = []
    for n, (tok, g) in enumerate(coins.items()):
        if not START <= g.ts.iloc[0] < END:
            continue
        ts, side, who = g.ts.values, g.side.values, g.trader.values
        usd = g.usd.fillna(0).values
        px = np.where((g.usd > 0) & (g.amount > 0), g.usd / g.amount.replace(0, np.nan), np.nan)
        buy = (side == 1) & ~np.isnan(px)
        bidx = np.nonzero(buy)[0]
        if len(bidx) < 2:
            continue
        bts, bpx = ts[bidx], px[bidx]
        held = np.minimum(bpx[:-1], bpx[1:])
        addr = names[tok]
        launch = launches.get(addr)
        buyers, order = set(), []
        for i in range(len(ts)):
            if side[i] == 1 and who[i] not in buyers:
                buyers.add(who[i])
                order.append(i)
        for k in KS:
            if len(order) < k:
                break
            i = order[k - 1]
            t = ts[i]
            nb = bisect.bisect_right(bts, t)  # buys up to now
            if nb < 2:
                continue  # (no condition on later trades: a coin nobody buys again is still a checkpoint)
            p_now = float(bpx[nb - 1])  # the alert shows the last price (a median of 3 lags a rising coin: fake 2x)
            end = bisect.bisect_right(bts, t + HORIZON)
            fut = held[nb:end - 1] if end - 1 > nb else np.array([0.0])
            hit = np.flatnonzero(held[nb:] >= 2 * p_now)  # held[j] = min of buys j, j+1, both after the checkpoint
            past = slice(0, i + 1)
            b_usd = usd[past][side[past] == 1]
            b_who = who[past][side[past] == 1]
            s_who = set(who[past][side[past] == 0])
            per = pd.Series(b_usd).groupby(b_who).sum()
            w5 = (ts[past] > t - 300)
            w10 = (ts[past] > t - 600)
            p5 = (ts[past] > t - 600) & (ts[past] <= t - 300)
            first_buyers = list(dict.fromkeys(b_who))[:k]
            rows.append({
                "coin": addr, "k": k, "ts": t,
                "peak": float(fut.max() / p_now),
                "t2x_h": (bts[nb + hit[0] + 1] - t) / 3600 if len(hit) else np.nan,
                "obs_h": (data_end - t) / 3600,
                "mins_to_k": (t - ts[0]) / 60,
                "trades_to_k": i + 1,
                "usd_all": float(b_usd.sum()),
                "usd_per_trade": float(b_usd.mean()),
                "max_buy": float(b_usd.max()),
                "top_buyer_share": float(per.max() / per.sum()) if per.sum() > 0 else 1.0,
                "repeat_buys": float((len(b_who) - len(set(b_who))) / len(b_who)),
                "sellers": len(s_who),
                "early_sold": float(np.mean([w in s_who for w in first_buyers])),
                "sell_usd_share": float(usd[past][side[past] == 0].sum() / max(1.0, usd[past].sum())),
                "buyers_5m": len(set(who[past][w5 & (side[past] == 1)])),
                "buyers_prev5m": len(set(who[past][p5 & (side[past] == 1)])),
                "usd_10m": float(usd[past][w10 & (side[past] == 1)].sum()),
                "fresh_share": float(np.mean([t - first_seen[w] < 86400 for w in set(b_who)])),
                "smart": sum(1 for w in set(b_who) if bisect.bisect_right(smart_known.get(w, []), t) > 0),
                "runup": float(p_now / bpx[0]),
                "off_high": float(p_now / held[:max(1, nb - 1)].max()) if nb > 2 else 1.0,
                "fdv": p_now * supply[addr] if addr in supply else np.nan,
                "is_pons": launch is not None,
                "launch_age_min": (t - launch[0]) / 60 if launch else np.nan,
                "launcher_prior": bisect.bisect_left(launcher_times[launch[1]], launch[0]) if launch else np.nan,
                "market_buyers_1h": np.nan,
            })
        if n % 5000 == 0:
            print(f"{n}/{len(coins)} coin · {len(rows)} kontrol noktası · {time.time() - t0:.0f} sn", flush=True)
    df = pd.DataFrame(rows)
    # market regime: distinct Fomo buyers across all coins in the hour before the checkpoint
    b = tr[tr.side == 1][["ts", "trader"]].sort_values("ts")
    hours = (b.ts // 3600).astype(int)
    per_hour = b.groupby(hours).trader.nunique()
    df["market_buyers_1h"] = (df.ts // 3600 - 1).astype(int).map(per_hour).values
    df.to_parquet(out)
    print(f"bitti: {len(df)} kontrol noktası, {df.coin.nunique()} coin ({time.time() - t0:.0f} sn)", flush=True)


if __name__ == "__main__":
    main()
