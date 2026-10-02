"""Holder, launch, liquidity and V4-hook checks for the security study, at the same moment (3rd Fomo buyer).

  python scripts/security_extra.py <trades.db> <security.parquet>

Adds columns to the parquet written by scripts/security_study.py (then `security_study.py report` shows them).
Needs the coins' Transfer logs (scripts/transfer_download.py, window: launch .. first Fomo trade + 1 h); only
logs up to the moment's block are used. Mirrors rhscanner/checks (holders.py, launch.py, liquidity.py):
- holders: balances at the moment; zero/dead = burned; Fomo contracts, V4 PoolManager, the coin, its curve and
  hook are system; other contracts (pools, routers, lockers) are not holders. `full` = logs start at the mint.
- creator: Pons launcher, else the sender of the first mint transaction. dev_initial = what the creator got in
  the first 30 blocks after the mint (not the mint itself), dev_pct = what it holds at the moment.
- bundle = wallets that got coins in the mint block, snipers = in the next 30 blocks (~3 s); their share now.
- depth: pool depth in $ per side from the price step of back-to-back Fomo buys in the 15 min before the moment
  (constant product: p1/p0 = (1 + x/R)^2).
- hook: the V4 pool's hook from Initialize events (non-Pons coins; a day before the first Fomo trade up to the
  moment); how many coins of the study use it; whether it is an EIP-1967 proxy.
Cached in DB tables `hooks_found`, `creators`, `codes`.
"""

import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from security_study import URLS, rpc_many  # noqa: E402
from rhscanner.checks.contract import EIP1967_IMPL_SLOT  # noqa: E402
from rhscanner.config import DEFAULT_V4_POOL_MANAGER  # noqa: E402
from rhscanner.fomo import FOMO_ENTRY, FOMO_EXECUTOR  # noqa: E402
from rhscanner.hooks import NAMED_HOOKS, TOPIC_V4_INITIALIZE  # noqa: E402

PM = DEFAULT_V4_POOL_MANAGER.lower()
ZERO = "0x" + "0" * 40
DEAD = "0x000000000000000000000000000000000000dead"
SYSTEM = {ZERO, DEAD, PM, FOMO_ENTRY.lower(), FOMO_EXECUTOR.lower()}
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_TOPIC = "0x" + "0" * 64
SNIPER_BLOCKS = 30
DAY_BLOCKS = 864_000
PUBLIC = URLS[:1]  # long-range log queries: dRPC's free tier answers them with errors
TOP = 15
EARLY = 30


def topic(addr):
    return "0x" + "0" * 24 + addr[2:]


def find_hooks(db, coins):
    db.execute("CREATE TABLE IF NOT EXISTS hooks_found (token TEXT PRIMARY KEY, hooks TEXT)")
    done = {t for (t,) in db.execute("SELECT token FROM hooks_found")}
    todo = coins[~coins.pons & ~coins.token.isin(done)]
    print(f"hook: {len(todo)} coin", flush=True)
    for n in range(0, len(todo), 100):
        part = todo.iloc[n:n + 100]
        calls = []
        for r in part.itertuples():
            rng = {"fromBlock": hex(int(r.first_block) - DAY_BLOCKS), "toBlock": hex(int(r.b0)), "address": PM}
            calls += [("eth_getLogs", [{**rng, "topics": [TOPIC_V4_INITIALIZE, None, topic(r.token)]}]),
                      ("eth_getLogs", [{**rng, "topics": [TOPIC_V4_INITIALIZE, None, None, topic(r.token)]}])]
        res = rpc_many(calls, size=4, urls=PUBLIC)
        rows = []
        for j, r in enumerate(part.itertuples()):
            a, b = res[2 * j], res[2 * j + 1]
            if a is None or b is None:
                continue  # refused: stays unknown
            logs = sorted(a + b, key=lambda e: int(e["blockNumber"], 16))
            # the pool the coin actually trades in is unknown here: take the latest hooked pool, else no hook
            hooks = ["0x" + e["data"][2 + 128:2 + 192][-40:] for e in logs]
            hooked = [h for h in hooks if h != ZERO]
            rows.append((r.token, hooked[-1] if hooked else (ZERO if hooks else "")))
        db.executemany("INSERT OR REPLACE INTO hooks_found VALUES (?, ?)", rows)
        db.commit()
    return dict(db.execute("SELECT token, hooks FROM hooks_found"))


def find_creators(db, coins):
    db.execute("CREATE TABLE IF NOT EXISTS creators (token TEXT PRIMARY KEY, creator TEXT, mint_block INTEGER)")
    done = {t for (t,) in db.execute("SELECT token FROM creators")}
    todo = coins[~coins.pons & ~coins.token.isin(done)]
    print(f"geliştirici: {len(todo)} coin", flush=True)
    for n in range(0, len(todo), 100):
        part = todo.iloc[n:n + 100]
        logs = rpc_many([("eth_getLogs", [{"fromBlock": hex(int(r.first_block) - 3600 * 10), "toBlock": hex(int(r.b0)),
                                           "address": r.token, "topics": [TRANSFER, ZERO_TOPIC]}])
                         for r in part.itertuples()], size=4, urls=PUBLIC)
        first = {}
        for r, lg in zip(part.itertuples(), logs):
            if lg:
                first[r.token] = (lg[0]["transactionHash"], int(lg[0]["blockNumber"], 16))
        txs = rpc_many([("eth_getTransactionByHash", [h]) for h, _ in first.values()], size=20)
        sender = {t: (tx or {}).get("from", "").lower() for t, tx in zip(first, txs)}
        rows = [(r.token, sender.get(r.token, ""), first.get(r.token, (None, None))[1])
                for r, lg in zip(part.itertuples(), logs) if lg is not None]  # refused queries stay unknown
        db.executemany("INSERT OR REPLACE INTO creators VALUES (?, ?, ?)", rows)
        db.commit()
    return {t: (c, b) for t, c, b in db.execute("SELECT token, creator, mint_block FROM creators")}


def is_contract(db, addrs):
    db.execute("CREATE TABLE IF NOT EXISTS codes (addr TEXT PRIMARY KEY, contract INTEGER)")
    known = dict(db.execute("SELECT addr, contract FROM codes"))
    todo = sorted(set(addrs) - set(known))
    print(f"kontrat mı: {len(todo)} adres", flush=True)
    def fetch(job):  # spread over both endpoints: each alone is slow (429 / 500)
        n, part = job
        return part, rpc_many([("eth_getCode", [a, "latest"]) for a in part], size=20, urls=URLS[n % 2:] + URLS[:n % 2])

    jobs = list(enumerate(todo[n:n + 100] for n in range(0, len(todo), 100)))
    with ThreadPoolExecutor(4) as pool:
        for k, (part, codes) in enumerate(pool.map(fetch, jobs)):
            rows = [(a, int(len(c or "0x") > 2)) for a, c in zip(part, codes) if c is not None]
            db.executemany("INSERT OR REPLACE INTO codes VALUES (?, ?)", rows)
            db.commit()
            known.update(rows)
            if k % 50 == 0:
                print(f"  {k * 100}/{len(todo)}", flush=True)
    return known


def depth_at(px, usd, ts, t0):
    m = (ts >= t0 - 900) & (ts <= t0)
    p, x = px[m], usd[m]
    est = []
    for i in range(1, len(p)):
        r = p[i] / p[i - 1] if p[i - 1] > 0 else np.nan
        if np.isfinite(r) and 1.001 < r < 3 and x[i] > 0:
            est.append(x[i] / (np.sqrt(r) - 1))
    return float(np.median(est)) if len(est) >= 2 else np.nan


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)
    path = sys.argv[2]
    df = pd.read_parquet(path)
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    ids = [names[t] for t in df.token]
    q = f"SELECT token, block, ts, side, usd, amount FROM trades WHERE token IN ({','.join(map(str, ids))}) ORDER BY token, ts"
    tr = pd.read_sql(q, db)
    by_id = {i: g for i, g in tr.groupby("token")}
    launch = {t: (b, c.lower(), l.lower()) for t, b, c, l in db.execute("SELECT lower(token), block, curve, launcher FROM launches")}
    supply = {a.lower(): r for a, r in db.execute("SELECT addr, raw FROM supply") if r}

    b0, first_block, depth = [], [], []
    for t, i, t0 in zip(df.token, ids, df.t0):
        g = by_id[i]
        first_block.append(int(g.block.iloc[0]))
        b0.append(int(g.block[g.ts <= t0].iloc[-1]))
        buys = g[(g.side == 1) & (g.amount > 0)]
        depth.append(depth_at((buys.usd / buys.amount).values, buys.usd.values, buys.ts.values, t0))
    df["b0"], df["first_block"], df["depth_usd"] = b0, first_block, depth

    hooks = find_hooks(db, df)
    creators = find_creators(db, df)

    # balances at the moment from the downloaded Transfer logs
    states, candidates = {}, set()
    for r in df.itertuples():
        tx = db.execute("SELECT block, src, dst, value FROM transfers WHERE token = ? AND block <= ? ORDER BY block, li",
                        (r.token, r.b0)).fetchall()
        if not tx:
            continue
        lb, curve, launcher = launch.get(r.token, (None, "", ""))
        if lb is None:
            creator, mint_block = creators.get(r.token, ("", None))
        else:
            creator, mint_block = launcher, lb
        mint_block = mint_block if mint_block is not None else (tx[0][0] if tx[0][1] == ZERO else None)
        full = mint_block is not None and tx[0][0] <= mint_block
        hook = hooks.get(r.token, "")
        system = SYSTEM | {r.token, curve, hook}
        bal = defaultdict(float)
        got_bundle, got_early, dev_initial = defaultdict(float), defaultdict(float), 0.0
        for blk, src, dst, val in tx:
            bal[src] -= val
            bal[dst] += val
            if mint_block is None or src == ZERO or dst in system:
                continue
            if dst == creator and blk <= mint_block + SNIPER_BLOCKS:
                dev_initial += val
            elif blk == mint_block:
                got_bundle[dst] += val
            elif blk <= mint_block + SNIPER_BLOCKS:
                got_early[dst] += val
        held = {a: v for a, v in bal.items() if v > 0 and a not in system}
        top = sorted(held, key=held.get, reverse=True)[:TOP]
        bundle = sorted(got_bundle, key=got_bundle.get, reverse=True)[:EARLY]
        early = sorted(got_early, key=got_early.get, reverse=True)[:EARLY]
        candidates.update(top, bundle, early)
        states[r.token] = dict(held=held, top=top, bundle=bundle, early=early, creator=creator, full=full,
                               dev_initial=dev_initial)
    contract = is_contract(db, candidates)

    out = []
    for r in df.itertuples():
        s = states.get(r.token)
        if not s or not s["full"]:  # logs not from the mint: balances incomplete, nothing measured
            out.append({"token": r.token, "full": bool(s and s["full"])})
            continue
        total = supply.get(r.token) or sum(v for v in s["held"].values())
        pct = lambda v: 100.0 * v / total if total else np.nan  # noqa: E731
        wallets = [a for a in s["top"] if contract.get(a) == 0]
        share = lambda ws: pct(sum(s["held"].get(a, 0) for a in ws if contract.get(a) == 0))  # noqa: E731
        dev_now = pct(s["held"].get(s["creator"], 0)) if s["creator"] else np.nan
        dev_init = pct(s["dev_initial"]) if s["creator"] else np.nan
        out.append({
            "token": r.token, "full": s["full"],
            "top10_pct": share(wallets[:10]), "largest_pct": share(wallets[:1]),
            "dev_pct": dev_now, "dev_initial_pct": dev_init,
            "dev_sold": bool(dev_init >= 1 and dev_now < dev_init / 2) if s["creator"] else None,
            "bundle_pct": share(s["bundle"]),
            "sniper_pct": share(s["early"]),
        })
    feats = pd.DataFrame(out)
    df = df.drop(columns=[c for c in feats.columns if c != "token" and c in df.columns]).merge(feats, on="token", how="left")

    # hooks: Pons coins trade on Pons' curve and graduate into Pons-hooked pools
    named = {h.lower() for h in NAMED_HOOKS}
    df["hook"] = [("pons" if p else hooks.get(t, "")) for t, p in zip(df.token, df.pons)]
    used = df.hook.value_counts()
    df["hook_coins"] = df.hook.map(used)
    plain = sorted(h for h in used.index if h.startswith("0x") and h != ZERO and h not in named)
    slots = rpc_many([("eth_getStorageAt", [h, EIP1967_IMPL_SLOT, "latest"]) for h in plain], size=20) if plain else []
    upgradeable = {h for h, v in zip(plain, slots) if v and int(v, 16)}
    df["hook_upgradeable"] = df.hook.isin(upgradeable)
    df["hook_named"] = df.hook.isin(named) | (df.hook == "pons")
    df.to_parquet(path, index=False)
    print("yazıldı", path, f"(holder ölçülen {int(df.full.fillna(False).sum())} / {len(df)} coin)")


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"{time.time() - t:.0f} sn")
