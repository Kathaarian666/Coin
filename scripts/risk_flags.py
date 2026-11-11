"""The bot's rug flag (rhscanner/live.risk_check, PROJE.md §0 B4) for a set of picks, for scorecard.py --risky.

  python scripts/risk_flags.py <trades.db> <picks.parquet> <out.parquet> <pool_depth cache.jsonl> [<cache> ...]

risky = the coin's latest V4 pool (Initialize up to the alert block, within live.POOL_LOOKBACK) has no hook, or its
owner() is set and not the launchpad's. Pools come from scripts/pool_depth.py's event caches (every pool of the coin
it found). owner() is read NOW: the public node keeps no historical state, so a coin whose owner renounced after the
alert counts as not risky (the flag is a lower bound there). Owners are cached in <out>.owners.json.
"""
import json
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import exit_truth as et  # noqa: E402
from rhscanner.live import LAUNCHPAD_OWNERS, POOL_LOOKBACK, ZERO  # noqa: E402

OWNER = "0x8da5cb5b"


def latest_hook(pools: dict, alert_block: int) -> str | None:
    """hooks of the coin's newest pool born in (alert - POOL_LOOKBACK, alert], None if there is none."""
    born = [(p["born"], p.get("hooks")) for p in pools.values()
            if alert_block - POOL_LOOKBACK <= p["born"] <= alert_block and p.get("hooks")]
    return max(born)[1].lower() if born else None


def is_risky(hook: str | None, owner: str | None) -> bool:
    return hook == ZERO or (owner is not None and owner != ZERO and owner not in LAUNCHPAD_OWNERS)


def owner_now(token: str) -> str | None:
    """owner() at the latest block; None when the call reverts (no owner()) or keeps failing."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                       "params": [{"to": token, "data": OWNER}, "latest"]}).encode()
    for i in range(6):
        url = et.URLS[i % len(et.URLS)]
        try:
            req = urllib.request.Request(url, body, {"content-type": "application/json", "user-agent": "curl/8.0"})
            res = json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:  # 429 / network: wait and retry
            time.sleep(min(10, 2 ** i))
            continue
        if "error" in res:
            return None  # reverted
        r = res.get("result") or ""
        return "0x" + r[-40:].lower() if len(r) >= 42 else None
    return None


def main():
    db = sqlite3.connect(sys.argv[1])
    picks = pd.read_parquet(sys.argv[2])
    picks["coin"] = picks.coin.str.lower()
    out = Path(sys.argv[3])
    pools = {}
    for cache in sys.argv[4:]:
        with open(cache) as f:
            for line in f:
                t, e = json.loads(line)
                pools[t] = {k: {"born": v["born"], "hooks": v.get("hooks")} for k, v in e.get("pools", {}).items()}
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}
    own_path = out.with_suffix(".owners.json")
    owners = json.loads(own_path.read_text()) if own_path.exists() else {}
    todo = sorted(set(picks.coin) - set(owners))
    print(f"{len(picks)} seçim · owner() okunacak {len(todo)} coin", flush=True)
    with ThreadPoolExecutor(4) as pool:
        for n, (c, o) in enumerate(zip(todo, pool.map(owner_now, todo))):
            owners[c] = o
            if n % 100 == 0:
                own_path.write_text(json.dumps(owners))
    own_path.write_text(json.dumps(owners))
    rows = []
    for r in picks.itertuples():
        ab = db.execute("SELECT MAX(block) FROM trades WHERE token=? AND ts<=?", (names[r.coin], r.ts)).fetchone()[0]
        hook = latest_hook(pools.get(r.coin, {}), ab) if r.coin in pools else None
        rows.append({"coin": r.coin, "ts": r.ts, "hook": hook, "owner": owners.get(r.coin),
                     "in_cache": r.coin in pools, "risky": is_risky(hook, owners.get(r.coin))})
    d = pd.DataFrame(rows)
    d.to_parquet(out, index=False)
    print(f"riskli {d.risky.sum()} / {len(d)} · hook yok {(d.hook == ZERO).sum()} · havuz yok {d.hook.isna().sum()} · "
          f"önbellekte olmayan {(~d.in_cache).sum()} · launchpad dışı sahip "
          f"{d.owner.map(lambda o: o is not None and o != ZERO and o not in LAUNCHPAD_OWNERS).sum()}")


if __name__ == "__main__":
    main()
