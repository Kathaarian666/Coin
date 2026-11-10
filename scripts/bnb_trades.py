"""BNB Chain Fomo trades in the research trades-DB format (scripts/fomo_download.py), so the Robinhood scripts
(winner_study.py, profit_study.py, scorecard.py) run on them unchanged (PROJE.md §0 sıradaki iş 2, 10 Nov).

  python scripts/bnb_trades.py <veri folder> <out.db>

Input: the `veri` branch's bnb/<day>/ files (rhscanner/bnb.py collector): Fomo event legs, USDC transfers to the
executor, flap.sh launches. Per transaction, like rhscanner.fomo.parse_fomo_logs:
- buy: a coin leg from an executor to a wallet (the wallet = trader)
- sell: a coin leg on an entry contract from a wallet to an executor
- usd: the largest USDC amount moving to the executor in the transaction (USDC has 18 decimals on BNB); trades paid
  in BNB (cash token 0x0) get no usd (no price, but the buyer still counts)
launches(token, ts, launcher) = flap.sh launches (creator as the launcher), in the column names winner_study reads;
supply stays empty (fdv NaN). Times are the collector's interpolated block times.
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fomo_download import SCHEMA  # noqa: E402
from rhscanner import bnb  # noqa: E402

EXECUTORS = {bnb.FOMO_EXECUTOR, bnb.FOMO_EXECUTOR_2}
ENTRIES = {bnb.FOMO_ENTRY, bnb.FOMO_ENTRY_2}
CASH = {bnb.USDC, "0x" + "0" * 40, "0xbb4cdb9cbd36b01bd8cbae1bc2b4f2c3a2ae8f0d"}  # USDC, BNB, WBNB


def legs_to_trades(legs: pd.DataFrame, usdc_in: pd.DataFrame) -> pd.DataFrame:
    usd = pd.concat([usdc_in[["tx", "amount"]],
                     legs[legs.token == bnb.USDC][["tx", "amount"]]]).groupby("tx").amount.max() / 1e18
    coin = legs[~legs.token.isin(CASH)]
    buy = coin[coin.src.isin(EXECUTORS) & ~coin.dst.isin(EXECUTORS)].assign(side=1, trader=lambda d: d.dst)
    sell = coin[coin.emitter.isin(ENTRIES) & coin.dst.isin(EXECUTORS)].assign(side=0, trader=lambda d: d.src)
    out = pd.concat([buy, sell])
    out["usd"] = out.tx.map(usd)
    return out[["block", "ts", "token", "side", "trader", "usd", "amount", "tx", "li"]]


def main():
    src, db = Path(sys.argv[1]) / "bnb", sqlite3.connect(sys.argv[2])
    db.executescript(SCHEMA)
    db.execute("CREATE TABLE IF NOT EXISTS supply (addr TEXT PRIMARY KEY, raw REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS launches (token TEXT PRIMARY KEY, block INTEGER, ts REAL, launcher TEXT)")
    trades, launches = [], []
    for day in sorted(p for p in src.iterdir() if p.is_dir()):
        legs = pd.concat([pd.read_csv(f) for f in sorted(day.glob("fomo_*.csv.gz"))])
        usdc = pd.read_csv(day / "usdc_in.csv.gz")
        t = legs_to_trades(legs, usdc)
        trades.append(t)
        launches.append(pd.read_csv(day / "launches.csv.gz"))
        print(f"{day.name}: {len(legs):,} ayak → {len(t):,} işlem", flush=True)
    tr = pd.concat(trades).drop_duplicates(["tx", "li"]).sort_values(["ts", "li"])
    names = {}
    for kind, col in (("token", "token"), ("wallet", "trader")):
        for a in pd.unique(tr[col]):
            names[(kind, a)] = db.execute("INSERT INTO names (kind, addr) VALUES (?, ?)", (kind, a)).lastrowid
        tr[col] = tr[col].map(lambda a, k=kind: names[(k, a)])
    db.executemany("INSERT INTO trades (block, ts, token, side, trader, usd, amount) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   tr[["block", "ts", "token", "side", "trader", "usd", "amount"]].itertuples(index=False))
    la = pd.concat(launches).drop_duplicates("token")
    db.executemany("INSERT OR IGNORE INTO launches (token, block, ts, launcher) VALUES (?, ?, ?, ?)",
                   la[["token", "block", "ts", "creator"]].itertuples(index=False))
    db.commit()
    print(f"bitti: {len(tr):,} işlem, {tr.token.nunique():,} coin, {len(la):,} flap.sh lansmanı")


if __name__ == "__main__":
    main()
