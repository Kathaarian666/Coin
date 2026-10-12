"""Cüzdan başına ham swap listesi (son WINDOW_DAYS gün) — önbellekli.

Her cüzdan için trades/{cüzdan}.json: SOL(+wSOL) karşılığı tek tokenlık alım/satımlar
(t, mint, yön, miktar, sol, imza) ve kapsama bilgisi. Günde BOT_TX_PER_DAY'den fazla işlem
yapan cüzdanlarda ilk sayfada durulur (bot). Kullanım: python3 trades.py cüzdanlar.txt
"""
import json, os, sys, time, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hl
from concurrent.futures import ThreadPoolExecutor

WSOL = "So11111111111111111111111111111111111111112"
STABLE = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
          "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"}
WINDOW_DAYS = 21
MAX_PAGES = 30           # 3.000 işlem: günde ~140 işleme kadar 21 günün tamamı
BOT_TX_PER_DAY = 500
HEAVY_TX_PER_DAY = 150     # 3. sayfada bu hızın üstündeyse 21 güne inemez: "yogun" deyip dur
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "trades")
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
    return sol, {k: v for k, v in d.items() if abs(v) > 1e-9}, keys[0] == w

def fetch(w, now=None):
    path = os.path.join(OUT, w + ".json")
    if os.path.exists(path): return json.load(open(path))
    now = now or time.time(); since = now - WINDOW_DAYS * 86400
    rows = []; n = 0; other = 0; oldest = newest = None; pg = None; status = "tamam"; failed = 0
    for page in range(MAX_PAGES):
        o = dict(OPTS)
        if pg: o["paginationToken"] = pg
        r = hl.rpc("getTransactionsForAddress", [w, o])
        if r is None: status = "rpc_hata"; break
        data = r.get("data") or []
        done = False
        for tx in data:
            t = tx["blockTime"]
            if t < since: done = True; break
            n += 1; oldest = t; newest = newest or t
            if tx["meta"].get("err"): failed += 1; continue
            sol, toks, signer = deltas(tx, w)
            toks = {k: v for k, v in toks.items() if k not in STABLE}
            if len(toks) != 1 or abs(sol) < 0.002: other += 1; continue
            (mint, q), = toks.items()
            if q > 0 and sol < 0: side = "B"
            elif q < 0 and sol > 0: side = "S"
            else: other += 1; continue
            rows.append([t, mint, side, abs(q), abs(sol), tx["transaction"]["signatures"][0], int(signer)])
        if page == 0 and len(data) == 100 and data[0]["blockTime"] - data[-1]["blockTime"] < 86400 * 100 / BOT_TX_PER_DAY:
            status = "bot"; break
        if page == 2 and data and newest - data[-1]["blockTime"] < 86400 * 300 / HEAVY_TX_PER_DAY:
            status = "yogun"; break
        pg = r.get("paginationToken")
        if done or not pg or not data: break
        if page == MAX_PAGES - 1: status = "sinir"
    res = dict(wallet=w, fetched=int(now), since=int(since), status=status, txs=n, failed=failed, other=other,
               oldest=oldest, newest=newest, pages=page + 1, rows=rows[::-1])
    if status == "rpc_hata": return res
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(path, "w"), separators=(",", ":"))
    return res

if __name__ == "__main__":
    ws = [l.split()[0] for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
    now = time.time(); t0 = time.time(); st = collections.Counter()
    with ThreadPoolExecutor(6) as ex:
        for i, r in enumerate(ex.map(lambda w: fetch(w, now), ws), 1):
            st[r["status"]] += 1
            if i % 50 == 0 or i == len(ws):
                print(f"{i}/{len(ws)} {dict(st)} rpc={hl.CALLS['n']} {time.time()-t0:.0f}s", flush=True)
