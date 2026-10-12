"""Son DAYS günde pump.fun bonding curve'ünü tamamlayıp (Migrate) borsaya geçen tokenler → grads.json"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hl
MIGRATOR = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
WSOL = "So11111111111111111111111111111111111111112"
DAYS = 21
since = time.time() - DAYS * 86400; out = {}; pg = None
for page in range(400):
    o = {"limit": 100, "transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "sortOrder": "desc"}
    if pg: o["paginationToken"] = pg
    r = hl.rpc("getTransactionsForAddress", [MIGRATOR, o])
    if not r or not r.get("data"): break
    for tx in r["data"]:
        if tx["blockTime"] < since: pg = None; break
        if tx["meta"].get("err"): continue
        if not any("Instruction: Migrate" in l for l in tx["meta"].get("logMessages") or []): continue
        for b in tx["meta"].get("postTokenBalances") or []:
            if b["mint"] != WSOL: out.setdefault(b["mint"], tx["blockTime"])
    else:
        pg = r.get("paginationToken")
    if not pg: break
    if page % 20 == 0: print(page, len(out), time.strftime("%m-%d %H:%M", time.gmtime(r["data"][-1]["blockTime"])), flush=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "grads.json"), "w"))
print("mezun token:", len(out), "çağrı:", hl.CALLS["n"])
