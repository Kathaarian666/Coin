import json, sys, os, hl
from concurrent.futures import ThreadPoolExecutor

WINDOW = 1800  # first 30 minutes
OPTS = {"sortOrder": "asc", "limit": 100, "transactionDetails": "full",
        "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}

def lamports_delta(tx, who):
    keys = [k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
    if who not in keys: return 0
    i = keys.index(who); m = tx["meta"]
    return (m["postBalances"][i] - m["preBalances"][i]) / 1e9

def tok_delta(tx, mint, owner):
    m = tx["meta"]; pre = post = 0.0
    for b in m.get("preTokenBalances") or []:
        if b["mint"] == mint and b.get("owner") == owner: pre += b["uiTokenAmount"]["uiAmount"] or 0
    for b in m.get("postTokenBalances") or []:
        if b["mint"] == mint and b.get("owner") == owner: post += b["uiTokenAmount"]["uiAmount"] or 0
    return post - pre

def scan(token):
    out = os.path.join("early", token + ".json")
    if os.path.exists(out): return json.load(open(out))
    rows = []; t0 = s0 = None; token_pg = None; creator = None
    for page in range(40):
        o = dict(OPTS)
        if token_pg: o["paginationToken"] = token_pg
        r = hl.rpc("getTransactionsForAddress", [token, o])
        if not r or not r.get("data"): break
        stop = False
        for tx in r["data"]:
            if t0 is None:
                t0, s0 = tx["blockTime"], tx["slot"]
                creator = tx["transaction"]["message"]["accountKeys"][0]["pubkey"]
            if tx["blockTime"] - t0 > WINDOW: stop = True; break
            if tx["meta"].get("err"): continue
            payer = tx["transaction"]["message"]["accountKeys"][0]["pubkey"]
            td = tok_delta(tx, token, payer)
            if abs(td) < 1e-9: continue
            rows.append(dict(sig=tx["transaction"]["signatures"][0], slot_off=tx["slot"] - s0,
                             sec_off=tx["blockTime"] - t0, payer=payer, tok=td,
                             sol=lamports_delta(tx, payer)))
        token_pg = r.get("paginationToken")
        if stop or not token_pg: break
    res = dict(token=token, creator=creator, t0=t0, rows=rows, pages=page + 1)
    json.dump(res, open(out, "w"))
    return res

if __name__ == "__main__":
    os.makedirs("early", exist_ok=True)
    toks = [l.split()[0] for l in open(sys.argv[1]) if l.strip()]
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(scan, toks):
            print(r["token"][:8], "creator", (r["creator"] or "")[:8], "pages", r["pages"], "trades", len(r["rows"]), flush=True)
    print("rpc calls:", hl.CALLS["n"])
