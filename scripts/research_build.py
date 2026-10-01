"""Build the research table: one row per candidate moment, with order-flow features and real outcomes.

  python scripts/research_build.py <out.parquet> <trades.db> [<trades.db> ...]

Candidates: for each coin, the first buy in each minute with at least 3 distinct buyers in the last 5
minutes. Features: rhscanner.flow.flow_features (plus `smart10`: buyers in the last 10 minutes with 2+ past
early-buy wins - a wallet's first buy in a coin that held 2x within the hour, known only once that hour is
over). Outcomes: scripts/fomo_replay.outcome (first buy 30/60 s later, 2x/3x on two buys in a row, else the
median price around the hour), as $ on $100 with Fomo's fee.
"""

import bisect
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fomo_replay import FEE_MIN, FEE_PCT, POSITION, outcome  # noqa: E402
from rhscanner.flow import flow_features  # noqa: E402
from rhscanner.strategy import trade_pnl  # noqa: E402

DELAYS = (30, 60)
TARGETS = (2.0, 3.0)
WIN_MULTIPLE = 2.0


def load(paths):
    coins: dict[str, list] = defaultdict(list)
    traders: dict[str, int] = {}
    for path in paths:
        db = sqlite3.connect(path)
        names = {(k, i): a for i, k, a in db.execute("SELECT id, kind, addr FROM names")}
        for ts, tok, side, trd, usd, amount in db.execute("SELECT ts, token, side, trader, usd, amount FROM trades"):
            who = traders.setdefault(names[("trader", trd)], len(traders))
            coins[names[("token", tok)]].append((ts, side, who, usd, (usd / amount) if usd and amount else None))
    for rows in coins.values():
        rows.sort(key=lambda r: r[0])
    return coins


def wallet_wins(coins):
    """Each wallet's early-buy wins as the times they became known (first buy + 1 h), sorted."""
    wins = defaultdict(list)
    for rows in coins.values():
        ts = np.array([r[0] for r in rows if r[1] and r[4]])
        px = np.array([r[4] for r in rows if r[1] and r[4]])
        who = [r[2] for r in rows if r[1] and r[4]]
        if len(px) < 3:
            continue
        held = np.minimum(px[:-1], px[1:])
        seen = set()
        for k, w in enumerate(who):
            if w in seen:
                continue
            seen.add(w)
            end = np.searchsorted(ts, ts[k] + 3600, side="right")
            if end - 1 > k + 1 and held[k + 1:end - 1].max() >= WIN_MULTIPLE * px[k]:
                wins[w].append(ts[k] + 3600)
    for w in wins:
        wins[w].sort()
    return lambda w, t: bisect.bisect_right(wins[w], t) if w in wins else 0


def main():
    out, paths = sys.argv[1], sys.argv[2:]
    t0 = time.time()
    coins = load(paths)
    print(f"{len(coins)} coin yüklendi ({time.time() - t0:.0f} sn)", flush=True)
    wins = wallet_wins(coins)
    print(f"cüzdan geçmişi hazır ({time.time() - t0:.0f} sn)", flush=True)
    records = []
    for n, (coin, rows) in enumerate(coins.items()):
        if len(rows) < 5:
            continue
        ts = [r[0] for r in rows]
        side = [r[1] for r in rows]
        trader = [r[2] for r in rows]
        usd = [r[3] for r in rows]
        price = [r[4] for r in rows]
        first_price = next((p for s, p in zip(side, price) if s and p), None)
        minute_done = -1
        for i in range(len(rows)):
            if not side[i] or int(ts[i] // 60) == minute_done:
                continue
            lo = bisect.bisect_right(ts, ts[i] - 300)
            if len({trader[j] for j in range(lo, i + 1) if side[j]}) < 3:
                continue
            minute_done = int(ts[i] // 60)
            res = {d: outcome(ts, side, price, ts[i], d, TARGETS) for d in DELAYS}
            if res[DELAYS[0]] is None:
                continue
            f = flow_features(ts, side, trader, usd, price, i, ts[0], first_price, wins)
            f.update({"coin": coin, "ts": ts[i]})
            for d in DELAYS:
                r = res[d]
                for target in TARGETS:
                    f[f"pnl_{d}_{target:g}x"] = (trade_pnl([(1.0, r[target])], POSITION, FEE_PCT, FEE_MIN)
                                                  if r else np.nan)
                f[f"peak_{d}"] = r["peak"] if r else np.nan
                f[f"at60_{d}"] = r["at60"] if r else np.nan
            records.append(f)
        if n % 3000 == 0:
            print(f"{n}/{len(coins)} coin · {len(records)} an · {time.time() - t0:.0f} sn", flush=True)
    df = pd.DataFrame.from_records(records)
    df["coin"] = df["coin"].astype("category")
    df.to_parquet(out)
    print(f"bitti: {len(df)} an, {df['coin'].nunique()} coin ({time.time() - t0:.0f} sn)", flush=True)


if __name__ == "__main__":
    main()
