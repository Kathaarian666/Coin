"""Full-market Robinhood Chain trades of the Fomo coins up to their k-th Fomo buyer (PROJE.md §4.9): Fomo makes only
~10-21 % of the swaps (§4.5e), and the paper-test model sees only Fomo's. Free: the chain's own RPC (public node,
dRPC as a fallback; Bitquery would cost money). The user can only trade coins listed on Fomo, so the coins stay the
same - only what is known about them at the moment grows.

  python scripts/rh_market.py download <fomo.db> <winners.parquet> <out.jsonl> [k=5] [workers=4]
  python scripts/rh_market.py features <fomo.db> <winners.parquet> <market.jsonl> <out.parquet> [k=5]

download: per coin with a k-th-buyer moment (scripts/winner_study.py), from its launch (a Pons coin) or an hour before
its first Fomo trade (any other) to the moment's block:
- Pons coins: every trade on its bonding curve, CurveBuy / CurveSell (topic2 = the wallet; data: ETH, tokens, fee,
  tax), identified on the chain 11 Oct (the old pons.py was gone)
- Uniswap V4: every Swap of the coin's pools (scripts/exit_truth.py find_pools; the event has no wallet, only the
  router: counts, sizes and direction)
One line per coin (resumable): {"coin", "block", "curve": [[block, 1 buy / 0 sell, wallet, eth], ...],
"swaps": [[block, 1 buy / 0 sell, quote amount (raw units of the pool's other currency)], ...]}.
features: the moment's full-market criteria (m_*), merged into the winners rows of that k; NaN where unknown.
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exit_truth as et  # noqa: E402
from rhscanner.hooks import TOPIC_V4_INITIALIZE  # noqa: E402

et.TOPIC_V4_INITIALIZE = TOPIC_V4_INITIALIZE

CURVE_BUY, CURVE_SELL = et.CURVE_BUY, et.CURVE_SELL  # as scripts/exit_truth.py (checked on the chain 11 Oct)
BLOCKS_PER_S = 10.0
LOOKBACK = 36_000  # blocks (~1 h) before the first Fomo trade of a coin that is not a Pons launch


def signed(word: int) -> int:
    return word - (1 << 256) if word >> 255 else word


def moments(db, winners: str, k: int) -> pd.DataFrame:
    """The k-th-buyer moments with their block (the coin's last Fomo trade at the moment) and the start block."""
    w = pd.read_parquet(winners, columns=["coin", "k", "ts", "is_pons"]).query("k == @k").drop_duplicates("coin")
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    launches = {t: (c.lower(), b) for t, c, b in db.execute("SELECT lower(token), curve, block FROM launches")}
    rows = []
    for r in w.itertuples():
        tid = names.get(r.coin.lower())
        if tid is None:
            continue
        first, block = db.execute("SELECT MIN(block), MAX(CASE WHEN ts <= ? THEN block END) FROM trades WHERE token = ?",
                                  (r.ts, tid)).fetchone()
        curve, launch = launches.get(r.coin.lower(), (None, None))
        rows.append({"coin": r.coin.lower(), "ts": r.ts, "block": block, "first": first, "curve": curve or "",
                     "start": launch if launch else max(0, first - LOOKBACK)})
    return pd.DataFrame(rows)


def pools_after(token: str, lo: int, hi: int) -> dict:
    """A Pons coin's V4 pools (its graduation) between its launch and the moment: {pool id: (token is currency0,
    creation block)}. et.find_pools would also search 2M blocks back, ~40 rate-limited queries for nothing."""
    t = "0x" + "0" * 24 + token[2:].lower()
    found = {}
    for topics in ([et.TOPIC_V4_INITIALIZE, None, t], [et.TOPIC_V4_INITIALIZE, None, None, t]):
        for e in et.logs(lo, hi, topics, et.PM):
            found[e["topics"][1]] = (e["topics"][2][-40:] == token[2:].lower(), int(e["blockNumber"], 16))
    return found


def one(r) -> dict:
    curve = []
    if r.curve:
        for e in et.logs(int(r.start), int(r.block), [[CURVE_BUY, CURVE_SELL]], r.curve):
            curve.append([int(e["blockNumber"], 16), int(e["topics"][0] == CURVE_BUY), "0x" + e["topics"][2][-40:],
                          et.word(e["data"], 0) / 1e18])
    pools = pools_after(r.coin, int(r.start), int(r.block)) if r.curve else et.find_pools(r.coin, int(r.first), int(r.block))
    swaps = []
    for pid, (token_is_0, born) in pools.items():
        for e in et.logs(max(born, int(r.start)), int(r.block), [et.SWAP, pid], et.PM):
            a0, a1 = signed(et.word(e["data"], 0)), signed(et.word(e["data"], 1))
            tok, quote = (a0, a1) if token_is_0 else (a1, a0)
            swaps.append([int(e["blockNumber"], 16), int(tok > 0), abs(quote)])
    return {"coin": r.coin, "block": int(r.block), "curve": curve, "swaps": swaps}


def download(db_path: str, winners: str, out: str, k: int = 5, workers: int = 4):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    db = sqlite3.connect(db_path)
    m = moments(db, winners, k)
    done = {json.loads(line)["coin"] for line in open(out)} if Path(out).exists() else set()
    todo = m[~m.coin.isin(done)].sort_values("curve", ascending=False, key=lambda c: c != "")  # Pons coins first: fast
    print(f"{len(m)} an, {len(done)} hazır, {len(todo)} kaldı ({(todo.curve != '').sum()} Pons)", flush=True)
    with open(out, "a") as f, ThreadPoolExecutor(workers) as pool:
        jobs = [pool.submit(one, r) for r in todo.itertuples()]
        for n, job in enumerate(as_completed(jobs), 1):
            try:
                f.write(json.dumps(job.result()) + "\n")
                f.flush()
            except Exception as exc:  # left for the next run (resumable)
                print("hata:", str(exc)[:120], flush=True)
            if n % 200 == 0:
                print(f"{n}/{len(todo)}", flush=True)


def coin_features(x: dict, fomo_blocks: np.ndarray) -> dict:
    """Full-market criteria at the moment (block x['block']); fomo_blocks: the coin's Fomo trades up to it."""
    b = x["block"]
    cv = np.array([[c[0], c[1], c[3]] for c in x["curve"]], float).reshape(-1, 3)
    wallets = [c[2] for c in x["curve"]]
    sw = np.array([[s[0], s[1]] for s in x["swaps"]], float).reshape(-1, 2)
    blk = np.concatenate([cv[:, 0], sw[:, 0]])
    buy = np.concatenate([cv[:, 1], sw[:, 1]]) == 1
    n = len(blk)
    win = blk > b - 300 * BLOCKS_PER_S
    out = {"m_trades": n, "m_buys": int(buy.sum()), "m_sell_share": float((~buy).mean()) if n else np.nan,
           "m_trades_5m": int(win.sum()), "m_buys_5m": int((buy & win).sum()),
           "m_fomo_share": len(fomo_blocks) / n if n else np.nan,
           "m_minutes": (b - blk.min()) / BLOCKS_PER_S / 60 if n else np.nan,
           "m_same_block_buys": int(pd.Series(blk[buy]).duplicated(keep=False).sum()) if n else 0,
           "m_on_curve": int(len(cv) > 0)}
    if len(cv):  # Pons: wallets and ETH
        cb = cv[:, 1] == 1
        eth_by = pd.Series(cv[cb, 2]).groupby(pd.Series(wallets)[cb].values).sum() if cb.any() else pd.Series(dtype=float)
        out.update({"m_buyers": int(len(eth_by)), "m_eth_buy": float(cv[cb, 2].sum()),
                    "m_eth_sell": float(cv[~cb, 2].sum()),
                    "m_top_buyer_share": float(eth_by.max() / eth_by.sum()) if len(eth_by) and eth_by.sum() else np.nan,
                    "m_buyers_5m": int(len(set(np.array(wallets)[cb & (cv[:, 0] > b - 300 * BLOCKS_PER_S)])))})
    else:
        out.update(dict.fromkeys(["m_buyers", "m_eth_buy", "m_eth_sell", "m_top_buyer_share", "m_buyers_5m"], np.nan))
    return out


def features(db_path: str, winners: str, market: str, out: str, k: int = 5):
    db = sqlite3.connect(db_path)
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    rows = {}
    for line in open(market):
        x = json.loads(line)
        fb = np.array([b for (b,) in db.execute("SELECT block FROM trades WHERE token = ? AND block <= ?",
                                                (names[x["coin"]], x["block"]))], float)
        rows[x["coin"]] = coin_features(x, fb)
    w = pd.read_parquet(winners)
    w = w[w.k == k].copy()
    f = pd.DataFrame.from_dict(rows, orient="index")
    w = w.join(f, on=w.coin.str.lower())
    w.to_parquet(out, index=False)
    print(f"{len(w)} an, tüm-pazar verisi {w.m_trades.notna().sum()}", flush=True)


if __name__ == "__main__":
    mode, args = sys.argv[1], sys.argv[2:]
    if mode == "download":
        download(*args[:3], *(int(a) for a in args[3:5]))
    else:
        features(*args[:4], *(int(a) for a in args[4:5]))
