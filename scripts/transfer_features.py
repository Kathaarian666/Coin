"""Holder-side features at each winner_study checkpoint, from the coins' Transfer logs (scripts/transfer_download.py).

  python scripts/transfer_features.py <trades.db> <winners.parquet> <out.parquet> [<k>] [<hours>=1]

<k>: only that checkpoint. <hours>: the download window (scripts/transfer_download.py); a checkpoint later than that
after the coin's first Fomo trade gets no holder features (its logs would be incomplete), a rule that only uses
what is known at the checkpoint (PROJE.md §6 rule 10).

At the checkpoint block only: holders (positive balance, system addresses excluded), holders 10 minutes earlier,
top-10 holders' share of supply, the launcher's share and whether it sent tokens away, snipers' share (wallets
that got tokens in the first 5 blocks after launch), share of holders that are Fomo wallets, transfers in the
last 10 minutes. `full` = the logs start at the launch (balances complete).
"""

import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.config import DEFAULT_V4_POOL_MANAGER  # noqa: E402
from rhscanner.fomo import FOMO_ENTRY, FOMO_EXECUTOR  # noqa: E402

SYSTEM = {"0x" + "0" * 40, "0x000000000000000000000000000000000000dead", DEFAULT_V4_POOL_MANAGER.lower(),
          FOMO_ENTRY.lower(), FOMO_EXECUTOR.lower()}


def main():
    db = sqlite3.connect(sys.argv[1])
    wins = pd.read_parquet(sys.argv[2])
    if len(sys.argv) > 4:
        wins = wins[wins.k == int(sys.argv[4])]
    window = 3600 * (float(sys.argv[5]) if len(sys.argv) > 5 else 1.0)
    t0 = time.time()
    sample = np.array(db.execute("SELECT block, ts FROM trades WHERE rowid % 500 = 0 ORDER BY ts").fetchall(), float)
    to_block = lambda ts: np.interp(ts, sample[:, 1], sample[:, 0])  # noqa: E731
    supply = {a.lower(): r for a, r in db.execute("SELECT addr, raw FROM supply") if r}
    launch = {t: (b, c.lower(), l.lower()) for t, b, c, l in db.execute("SELECT lower(token), block, curve, launcher FROM launches")}
    fomo_wallets = {a.lower() for (a,) in db.execute("SELECT addr FROM names WHERE kind = 'trader'")}
    first = {a: (b, t) for a, b, t in db.execute("SELECT lower(n.addr), MIN(t.block), MIN(t.ts) FROM trades t "
                                                 "JOIN names n ON n.id = t.token WHERE n.kind = 'token' GROUP BY t.token")}
    first_block = {a: b for a, (b, _) in first.items()}
    token_id = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    out = []
    for n, (coin, g) in enumerate(wins.groupby("coin", sort=False)):
        tr = db.execute("SELECT block, li, src, dst, value FROM transfers WHERE token = ? ORDER BY block, li", (coin,)).fetchall()
        if not tr:
            continue
        blocks = np.array([r[0] for r in tr])
        lb, curve, launcher = launch.get(coin, (None, None, None))
        system = SYSTEM | {coin, curve} if curve else SYSTEM | {coin}
        full = lb is not None and lb >= first_block[coin] - 36000
        total = supply.get(coin) or max(1.0, sum(r[4] for r in tr if r[2] == "0x" + "0" * 40))
        snipers = {r[3] for r in tr if lb is not None and r[0] <= lb + 5 and r[3] not in system}
        # the checkpoint's own block (the last Fomo trade at or before it), not a block guessed from the time
        own = np.array(db.execute("SELECT ts, block FROM trades WHERE token = ? ORDER BY ts", (token_id[coin],)).fetchall())
        for _, row in g.iterrows():
            if row.ts > first[coin][1] + window:
                continue
            b_now = own[np.searchsorted(own[:, 0], row.ts, side="right") - 1, 1]
            b_10 = to_block(row.ts - 600)
            bal = defaultdict(float)
            holders_10 = None
            sent_by_launcher = 0.0
            cut = np.searchsorted(blocks, b_now, side="right")
            cut10 = np.searchsorted(blocks, b_10, side="right")
            for idx, (blk, li, src, dst, val) in enumerate(tr[:cut]):
                if idx == cut10:
                    holders_10 = sum(1 for a, v in bal.items() if v > 0 and a not in system)
                bal[src] -= val
                bal[dst] += val
                if launcher and src == launcher and dst not in ("0x" + "0" * 40,):
                    sent_by_launcher += val
            if holders_10 is None:
                holders_10 = sum(1 for a, v in bal.items() if v > 0 and a not in system)
            held = {a: v for a, v in bal.items() if v > 0 and a not in system}
            top = sorted(held.values(), reverse=True)
            out.append({
                "coin": coin, "k": row.k, "full": full,
                "holders": len(held), "holders_10m_ago": holders_10,
                "holder_growth_10m": len(held) - holders_10,
                "top10_pct": 100 * sum(top[:10]) / total,
                "top1_pct": 100 * (top[0] if top else 0) / total,
                "dev_pct": 100 * held.get(launcher, 0) / total if launcher else np.nan,
                "dev_sent_pct": 100 * sent_by_launcher / total if launcher else np.nan,
                "sniper_pct": 100 * sum(held.get(a, 0) for a in snipers) / total if full else np.nan,
                "fomo_holder_share": np.mean([a in fomo_wallets for a in held]) if held else np.nan,
                "transfers_10m": int(cut - cut10),
            })
        if n % 500 == 0:
            print(f"{n}/{wins.coin.nunique()} coin · {time.time() - t0:.0f} sn", flush=True)
    feats = pd.DataFrame(out)
    wins.merge(feats, on=["coin", "k"], how="left").to_parquet(sys.argv[3])
    print(f"bitti: {len(feats)} kontrol noktası ({time.time() - t0:.0f} sn)", flush=True)


if __name__ == "__main__":
    main()
