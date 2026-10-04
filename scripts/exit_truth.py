"""The real price at the exit times of the picks, from every on-chain trade, not only Fomo's (PROJE.md §0 A10).

  python scripts/exit_truth.py <trades.db> <picks.parquet> <out.parquet> [<min pct>=0.95]

exit_study.py values a position at the last Fomo price, which goes stale once Fomo users stop trading the coin:
others may still trade it (the price moved) or its liquidity may be gone. Here, for each pick and exit time
(1 / 3 / 6 / 24 h after the alert): the coin's on-chain trades from the alert on — Pons curve CurveBuy / CurveSell
(eth / tokens) and Uniswap V4 Swap of its pools (sqrtPriceX96) — give the price on the venue; the ratio
"venue price at the exit / venue price at the last Fomo trade before it" corrects the Fomo price. A V4 pool that lost
its liquidity (ModifyLiquidity with a negative delta, then no swap) values the coin at 0. Columns per exit h:
ratio_<h> (NaN = no venue price, e.g. the coin changed venue in between), pulled_<h> (liquidity removed before it),
onchain_<h> (number of on-chain trades between the last Fomo trade and the exit).
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
from eth_utils import keccak

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.config import DEFAULT_V4_POOL_MANAGER  # noqa: E402
from rhscanner.hooks import TOPIC_V4_INITIALIZE  # noqa: E402
from rhscanner.live import TOPIC_MODIFY_LIQUIDITY  # noqa: E402

URLS = ["https://rpc.mainnet.chain.robinhood.com", "https://robinhood.drpc.org"]
PM = DEFAULT_V4_POOL_MANAGER.lower()
CURVE_BUY = "0xec36bf571f136799e8dc0b0b8bea4b04d8bd3d43de838aab0d5fc21d4cbfc455"
CURVE_SELL = "0x8113d738abdcb6b38357e9d53a54a7157861a09031b453651f0fe7fe151f59df"
SWAP = "0x" + keccak(text="Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)").hex()
EXITS = (1, 3, 6, 24)
BLOCKS_PER_S = 9.93
PULL_SHARE = 0.2


def rpc(method, params, attempt_urls=URLS):
    err = None
    for i in range(8):
        url = attempt_urls[i % len(attempt_urls)]
        try:
            req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                          "params": params}).encode(),
                                         {"content-type": "application/json", "user-agent": "curl/8.0"})
            res = json.load(urllib.request.urlopen(req, timeout=90))
            if "error" in res:
                raise RuntimeError(str(res["error"]))
            return res["result"]
        except Exception as exc:
            err = exc
            if any(w in str(exc) for w in ("exceed", "limit", "too many", "10000", "range", "allowed")) and "429" not in str(exc):
                raise
            time.sleep(min(20, 2 ** i))
    raise RuntimeError(f"rpc failed: {err}")


CHUNK = 100_000  # blocks per address-filtered log query (the node refuses more)


def logs(lo, hi, topics, address):
    if hi - lo >= CHUNK:
        out = []
        for a in range(lo, hi + 1, CHUNK):
            out += logs(a, min(hi, a + CHUNK - 1), topics, address)
        return out
    try:
        return rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "topics": topics, "address": address}])
    except RuntimeError:
        if hi - lo < 50:
            raise
        mid = (lo + hi) // 2
        return logs(lo, mid, topics, address) + logs(mid + 1, hi, topics, address)


def word(data, i):
    return int(data[2 + 64 * i: 2 + 64 * (i + 1)], 16)


def venue_prices(token, curve, lo, hi):
    """[(block, log index, venue, price, kind)] kind 'trade' / 'pull'; price = quote raw per token raw."""
    out = []
    if curve:
        for e in logs(lo, hi, [[CURVE_BUY, CURVE_SELL]], curve):
            d = e["data"]
            eth, tok = (word(d, 0), word(d, 1)) if e["topics"][0] == CURVE_BUY else (word(d, 1), word(d, 0))
            if tok:
                out.append((int(e["blockNumber"], 16), int(e["logIndex"], 16), "curve", eth / tok, "trade"))
    t = "0x" + "0" * 24 + token[2:].lower()
    pools = {}
    for topics in ([TOPIC_V4_INITIALIZE, None, t], [TOPIC_V4_INITIALIZE, None, None, t]):
        for e in logs(max(0, lo - 2_000_000), hi, topics, PM):
            # token is currency0?, the pool's creation block
            pools[e["topics"][1]] = (e["topics"][2][-40:] == token[2:].lower(), int(e["blockNumber"], 16))
    for pid, (token_is_0, born) in pools.items():
        # liquidity moves between ranges all the time (launchpad hooks rebalance): a pull is the pool's NET
        # liquidity (every add and remove since its creation) falling under PULL_SHARE of its peak so far
        net, peak, pulled = 0, 0, False
        for e in logs(min(lo, born), hi, [[SWAP, TOPIC_MODIFY_LIQUIDITY], pid], PM):
            b, li = int(e["blockNumber"], 16), int(e["logIndex"], 16)
            if e["topics"][0] == SWAP:
                if b < lo:
                    continue
                sqrt = word(e["data"], 2)
                p10 = (sqrt / 2**96) ** 2  # currency1 per currency0 (raw)
                price = p10 if token_is_0 else (1 / p10 if p10 else 0)
                if price:
                    out.append((b, li, pid, price, "trade"))
            else:
                net += int.from_bytes(bytes.fromhex(e["data"][2 + 128: 2 + 192]), "big", signed=True)
                peak = max(peak, net)
                now_pulled = peak > 0 and net <= PULL_SHARE * peak
                if now_pulled and not pulled and b >= lo:
                    out.append((b, li, pid, 0.0, "pull"))
                pulled = now_pulled
    return sorted(out)


def one(args):
    token, curve, alert_block, fomo_blocks, end_block = args
    try:
        ev = venue_prices(token, curve, alert_block, end_block)
    except Exception as exc:
        return token, None, str(exc)[:100]
    return token, ev, None


def main():
    db = sqlite3.connect(sys.argv[1], timeout=300)
    picks = pd.read_parquet(sys.argv[2])
    picks = picks[picks.pct >= (float(sys.argv[4]) if len(sys.argv) > 4 else 0.95)].sort_values("ts")
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    curves = dict(db.execute("SELECT lower(token), lower(curve) FROM launches"))
    jobs, fomo = [], {}
    for r in picks.itertuples():
        f = np.array(db.execute("SELECT ts, block FROM trades WHERE token = ? ORDER BY ts", (names[r.coin],)).fetchall())
        fomo[r.coin] = f
        alert_block = int(f[f[:, 0] <= r.ts][-1, 1])
        jobs.append((r.coin, curves.get(r.coin), alert_block, None, alert_block + int(24 * 3600 * BLOCKS_PER_S) + 600))
    t0, results, failed = time.time(), {}, 0
    with ThreadPoolExecutor(4) as pool:
        for n, (token, ev, err) in enumerate(pool.map(one, jobs)):
            results[token] = ev
            failed += ev is None
            if n % 50 == 0:
                print(f"{n}/{len(jobs)} coin · {time.time() - t0:.0f} sn · hata {failed}", flush=True)
    rows = []
    for r, job in zip(picks.itertuples(), jobs):
        ev, f = results[r.coin], fomo[r.coin]
        row = {"coin": r.coin, "ts": r.ts, "pct": r.pct}
        alert_block = job[2]
        for h in EXITS:
            if ev is None:
                row.update({f"ratio_{h}": np.nan, f"pulled_{h}": np.nan, f"onchain_{h}": np.nan})
                continue
            exit_block = alert_block + int(h * 3600 * BLOCKS_PER_S)
            before = f[(f[:, 1] <= exit_block)]
            last_fomo = int(before[-1, 1])
            upto = [e for e in ev if e[0] <= exit_block]
            pulled = any(e[4] == "pull" for e in upto)
            trades = [e for e in upto if e[4] == "trade"]
            at_fomo = [e for e in trades if e[0] <= last_fomo]
            ratio = np.nan
            if trades and at_fomo and trades[-1][2] == at_fomo[-1][2] and at_fomo[-1][3]:
                ratio = trades[-1][3] / at_fomo[-1][3]
            elif trades and not at_fomo:
                ratio = np.nan
            elif not trades:
                ratio = 1.0  # nothing traded on the venue: its price did not move
            if pulled and (not trades or trades[-1][0] < max(e[0] for e in upto if e[4] == "pull")):
                ratio = 0.0
            row.update({f"ratio_{h}": ratio, f"pulled_{h}": pulled,
                        f"onchain_{h}": sum(1 for e in trades if e[0] > last_fomo)})
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_parquet(sys.argv[3], index=False)
    print(f"bitti: {len(out)} seçim, zincir verisi alınamayan {failed}")
    for h in EXITS:
        r = out[f"ratio_{h}"]
        print(f"  {h:2d} sa: gerçek/son Fomo fiyatı medyan {r.median():.2f}, çeyrekler {r.quantile(.25):.2f}–{r.quantile(.75):.2f}, "
              f"bilinmeyen %{100 * r.isna().mean():.0f}, likidite çekilmiş %{100 * out[f'pulled_{h}'].mean():.1f}, "
              f"Fomo'dan sonra zincirde işlem medyanı {out[f'onchain_{h}'].median():.0f}")


if __name__ == "__main__":
    main()
