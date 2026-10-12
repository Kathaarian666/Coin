"""swing_tokens.json'daki tokenlerde 21 güne yayılmış SAMPLES anda işlemleri örnekle; ≥MIN_SOL alım yapan
cüzdanları topla → swing_buyers.json {cüzdan: {mint: [alım sayısı, toplam SOL]}}"""
import json, os, sys, time, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hl
from trades import deltas, WSOL
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES, MIN_SOL, DAYS = 30, 0.5, 21
SKIP_SYM = {"USDG", "TRX"}
toks = [k for k in json.load(open(os.path.join(HERE, "swing_tokens.json"))) if k["symbol"].upper() not in SKIP_SYM]
now = time.time()

def sample(args):
    mint, t = args
    r = hl.rpc("getTransactionsForAddress", [mint, {"limit": 100, "sortOrder": "asc", "transactionDetails": "full",
               "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "filters": {"blockTime": {"gte": int(t)}}}])
    out = []
    for tx in (r or {}).get("data", []):
        if tx["meta"].get("err"): continue
        payer = tx["transaction"]["message"]["accountKeys"][0]["pubkey"]
        sol, tk, _ = deltas(tx, payer); q = tk.get(mint)
        if q and q > 0 and -sol >= MIN_SOL: out.append((payer, -sol))
    return mint, out

jobs = []
for k in toks:
    start = max(now - DAYS * 86400, k["created"] + 86400)
    jobs += [(k["mint"], start + i * (now - 3600 - start) / SAMPLES) for i in range(SAMPLES)]
B = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0]))
with ThreadPoolExecutor(6) as ex:
    for mint, out in ex.map(sample, jobs):
        for w, s in out: B[w][mint][0] += 1; B[w][mint][1] += s
json.dump({w: dict(v) for w, v in B.items()}, open(os.path.join(HERE, "swing_buyers.json"), "w"))
multi = [w for w, v in B.items() if len(v) >= 2]
print(f"token {len(toks)}, çağrı {hl.CALLS['n']}, alıcı {len(B)}, ≥2 tokende alan {len(multi)}")
