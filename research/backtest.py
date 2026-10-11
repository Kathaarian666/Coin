"""Copy-trade backtest: enter/exit N seconds after the tracked wallet, at market price."""
import json, os, sys, time, statistics, collections, hl
from concurrent.futures import ThreadPoolExecutor
from pnl import deltas, STABLE, SINCE

DELAYS = [30, 120]
MAX_TRADES = 25

def events(w, pages=8):
    out = os.path.join("ev", w + ".json")
    if os.path.exists(out): return json.load(open(out))
    ev = []; pg = None
    for _ in range(pages):
        o = {"sortOrder": "desc", "limit": 100, "transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}
        if pg: o["paginationToken"] = pg
        r = hl.rpc("getTransactionsForAddress", [w, o])
        if not r or not r.get("data"): break
        done = False
        for tx in r["data"]:
            if tx["blockTime"] < SINCE: done = True; break
            if tx["meta"].get("err"): continue
            sol, toks = deltas(tx, w)
            toks = {k: v for k, v in toks.items() if k not in STABLE}
            if len(toks) != 1 or abs(sol) < 0.002: continue
            (m, q), = toks.items()
            if (q > 0) == (sol < 0):
                ev.append(dict(t=tx["blockTime"], m=m, q=q, sol=sol))
        pg = r.get("paginationToken")
        if done or not pg: break
    ev.sort(key=lambda e: e["t"])
    json.dump(ev, open(out, "w")); return ev

def trades(ev):
    by = collections.defaultdict(list)
    for e in ev: by[e["m"]].append(e)
    res = []
    for m, es in by.items():
        buys = [e for e in es if e["q"] > 0]
        if not buys: continue
        t0 = buys[0]["t"]; bq = sum(e["q"] for e in buys); sin = sum(-e["sol"] for e in buys)
        sold = 0; texit = None; sout = sum(e["sol"] for e in es if e["q"] < 0)
        for e in es:
            if e["q"] < 0 and e["t"] >= t0:
                sold += -e["q"]
                if sold >= 0.5 * bq: texit = e["t"]; break
        if texit is None: continue
        res.append(dict(m=m, t_in=t0, t_out=texit, own_ret=sout / sin - 1 if sin > 0 else None,
                        own_px_in=buys[0]["sol"] / -buys[0]["q"] * -1))
    res.sort(key=lambda r: -r["t_in"])
    return res[:MAX_TRADES]

_pc = {}
def price_at(m, t):
    k = (m, t)
    if k in _pc: return _pc[k]
    r = hl.rpc("getTransactionsForAddress", [m, {"sortOrder": "asc", "limit": 25, "transactionDetails": "full",
               "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "filters": {"blockTime": {"gte": t}}}])
    px = []
    for tx in (r or {}).get("data", []):
        if tx["meta"].get("err") or tx["blockTime"] > t + 60: continue
        payer = tx["transaction"]["message"]["accountKeys"][0]["pubkey"]
        sol, toks = deltas(tx, payer)
        q = toks.get(m)
        if q and abs(sol) >= 0.01 and (q > 0) == (sol < 0): px.append(abs(sol) / abs(q))
        if len(px) >= 5: break
    v = statistics.median(px) if px else None
    _pc[k] = v; return v

def run(w):
    tr = trades(events(w)); out = []
    for t in tr:
        row = dict(t, copy={})
        for d in DELAYS:
            a, b = price_at(t["m"], t["t_in"] + d), price_at(t["m"], t["t_out"] + d)
            row["copy"][d] = (b / a - 1) if a and b else None
        out.append(row)
    return w, out

if __name__ == "__main__":
    os.makedirs("ev", exist_ok=True)
    ws = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    with ThreadPoolExecutor(3) as ex: res = dict(ex.map(run, ws))
    json.dump(res, open(sys.argv[2] if len(sys.argv)>2 else "backtest.json", "w"))
    FEE = 0.03  # ~1% per side + priority/slippage, round trip
    for w, rows in res.items():
        own = [r["own_ret"] for r in rows if r["own_ret"] is not None]
        line = f"{w[:10]} trades={len(rows)} own_med={statistics.median(own):+.0%} own_avg={statistics.mean(own):+.0%}" if own else f"{w[:10]} none"
        for d in DELAYS:
            c = [r["copy"][str(d)] if str(d) in r["copy"] else r["copy"][d] for r in rows]
            c = [x - FEE for x in c if x is not None]
            if c: line += f" | {d}s: n={len(c)} med={statistics.median(c):+.0%} avg={statistics.mean(c):+.0%} win={sum(x>0 for x in c)/len(c):.0%}"
        print(line)
    print("calls", hl.CALLS["n"])
