"""Per-wallet SOL-denominated swap P&L over recent history (up to MAX_PAGES*100 txs, max 30 days)."""
import json, os, sys, time, collections, hl
from concurrent.futures import ThreadPoolExecutor

WSOL = "So11111111111111111111111111111111111111112"
STABLE = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
          "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"}
MAX_PAGES = 4
SINCE = time.time() - 30 * 86400
OPTS = {"sortOrder": "desc", "limit": 100, "transactionDetails": "full",
        "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}

def deltas(tx, w):
    m = tx["meta"]; d = collections.defaultdict(float)
    for b in m.get("preTokenBalances") or []:
        if b.get("owner") == w: d[b["mint"]] -= b["uiTokenAmount"]["uiAmount"] or 0
    for b in m.get("postTokenBalances") or []:
        if b.get("owner") == w: d[b["mint"]] += b["uiTokenAmount"]["uiAmount"] or 0
    keys = [k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
    sol = 0.0
    if w in keys:
        i = keys.index(w); sol = (m["postBalances"][i] - m["preBalances"][i]) / 1e9
    sol += d.pop(WSOL, 0.0)
    return sol, {k: v for k, v in d.items() if abs(v) > 1e-9}

def wallet(w):
    out = os.path.join("pnl", w + ".json")
    if os.path.exists(out): return json.load(open(out))
    pos = collections.defaultdict(lambda: dict(bq=0.0, sq=0.0, sin=0.0, sout=0.0, first=None, last=None, nb=0, ns=0))
    n = 0; pg = None; oldest = None; hit_cap = False; stable_swaps = 0
    for page in range(MAX_PAGES):
        o = dict(OPTS)
        if pg: o["paginationToken"] = pg
        r = hl.rpc("getTransactionsForAddress", [w, o])
        if not r or not r.get("data"): break
        for tx in r["data"]:
            if tx["blockTime"] < SINCE: pg = None; break
            oldest = tx["blockTime"]; n += 1
            if tx["meta"].get("err"): continue
            sol, toks = deltas(tx, w)
            toks = {k: v for k, v in toks.items() if k not in STABLE}
            if len(toks) != 1: continue
            (mint, q), = toks.items()
            if abs(sol) < 0.002: stable_swaps += 1; continue   # not a SOL-quoted swap (or a transfer)
            p = pos[mint]; t = tx["blockTime"]
            p["first"] = t if p["first"] is None else min(p["first"], t); p["last"] = max(p["last"] or 0, t)
            if q > 0 and sol < 0: p["bq"] += q; p["sin"] += -sol; p["nb"] += 1
            elif q < 0 and sol > 0: p["sq"] += -q; p["sout"] += sol; p["ns"] += 1
        else:
            pg = r.get("paginationToken")
            if not pg: break
            if page == MAX_PAGES - 1: hit_cap = True
            continue
        break
    res = dict(wallet=w, txs=n, oldest=oldest, hit_cap=hit_cap, pos=dict(pos))
    json.dump(res, open(out, "w"))
    return res

def summarize(res):
    realized = 0.0; wins = losses = 0; closed = []; tokens = 0; holds = []
    for mint, p in res["pos"].items():
        if p["bq"] <= 0: continue
        tokens += 1
        if p["sq"] <= 0: continue
        frac = min(1.0, p["sq"] / p["bq"])
        pnl = p["sout"] - p["sin"] * frac
        realized += pnl; closed.append(pnl)
        wins += pnl > 0; losses += pnl <= 0
        if p["first"] and p["last"]: holds.append(p["last"] - p["first"])
    closed.sort(reverse=True)
    top2 = sum(closed[:2]); share = (top2 / realized) if realized > 0 else None
    days = (time.time() - res["oldest"]) / 86400 if res["oldest"] else 0
    holds.sort()
    return dict(wallet=res["wallet"], txs=res["txs"], days=round(days, 1), hit_cap=res["hit_cap"],
                tokens=tokens, closed=len(closed), win_rate=round(wins / len(closed), 2) if closed else None,
                realized_sol=round(realized, 2), top2_share=round(share, 2) if share else None,
                med_hold_min=round(holds[len(holds) // 2] / 60, 1) if holds else None,
                tok_per_day=round(tokens / days, 1) if days else None)

if __name__ == "__main__":
    os.makedirs("pnl", exist_ok=True)
    ws = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    with ThreadPoolExecutor(4) as ex:
        rows = [summarize(r) for r in ex.map(wallet, ws)]
    json.dump(rows, open(sys.argv[2], "w"), indent=0)
    print("rpc calls:", hl.CALLS["n"])
