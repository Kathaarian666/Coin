"""Anlık kopya simülasyonu: cüzdan bir tokene ilk girdiğinde t+Δ'da al, cüzdan pozisyonunun yarısını
sattığında satış+Δ'da sat (hiç satmadıysa güncel fiyat, metrics ile aynı kurallar). Fiyat = t+Δ'dan
sonraki ilk 3 gerçek swap'ın medyanı (15 sn içinde). Ücret+kayma: tek yön FEE.
Kullanım: python3 copysim.py cüzdan1 cüzdan2 ...  → copysim/{cüzdan}.json
"""
import json, os, sys, glob, statistics, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hl, metrics
from trades import WSOL
from concurrent.futures import ThreadPoolExecutor
HERE = metrics.HERE
DELAYS = (1, 3, 10)
FEE = 0.015
MAX_TOK = 40  # cüzdan başına en yeni 40 token (kredi sınırı)
SINCE = 1790812800  # 2026-10-01
PX = json.load(open(os.path.join(HERE, "prices.json")))["px"]
CACHE = os.path.join(HERE, "pricepath2"); os.makedirs(CACHE, exist_ok=True)

def pool_price(tx, mint):
    """Havuz tarafından fiyat (SOL/token): payer'ın tersine token değişimi olan sahibin (havuz) SOL + wSOL
    değişimi / token değişimi. Ücret ve Jito bahşişi havuza gitmediği için fiyatı bozmaz."""
    m = tx["meta"]; tok = collections.defaultdict(float); wsol = collections.defaultdict(float)
    for sign, key in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in m.get(key) or []:
            amt = sign * (b["uiTokenAmount"]["uiAmount"] or 0)
            if b["mint"] == mint: tok[b.get("owner")] += amt
            elif b["mint"] == WSOL: wsol[b.get("owner")] += amt
    keys = [k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
    payer = keys[0]
    pools = [(o, v) for o, v in tok.items() if o != payer and abs(v) > 1e-9]
    if not pools: return None, None
    pool, pv = max(pools, key=lambda x: abs(x[1]))
    ps = wsol.get(pool, 0.0)
    if pool in keys:
        i = keys.index(pool); ps += (m["postBalances"][i] - m["preBalances"][i]) / 1e9
    if abs(ps) < 0.005 or (pv > 0) == (ps > 0): return None, None  # havuz token alıyorsa SOL vermeli
    return abs(ps) / abs(pv), ("B" if pv < 0 else "S")

def swaps_after(mint, t):
    """t'den itibaren mint'teki swap'lar: [(blockTime, havuz fiyatı, yön)] (önbellekli)."""
    path = os.path.join(CACHE, f"{mint}_{t}.json")
    if os.path.exists(path): return json.load(open(path))
    r = hl.rpc("getTransactionsForAddress", [mint, {"limit": 40, "sortOrder": "asc", "transactionDetails": "full",
               "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "filters": {"blockTime": {"gte": int(t)}}}])
    out = []
    for tx in (r or {}).get("data", []):
        if tx["meta"].get("err"): continue
        p, side = pool_price(tx, mint)
        if p: out.append((tx["blockTime"], p, side))
    json.dump(out, open(path, "w"))
    return out

def price(sw, t):
    p = [x[1] for x in sw if t <= x[0] <= t + 15][:3]
    return statistics.median(p) if p else None

def sim_token(mint, ts):
    """ts: cüzdanın bu tokendeki [(t, side, q, sol)]"""
    bq = sq = 0.0; entry = ts[0][0] if ts[0][1] == "B" else None; exit_t = None
    for t, s, q, sol in ts:
        if s == "B": bq += q
        else:
            sq += q
            if exit_t is None and bq > 0 and sq >= 0.5 * bq: exit_t = t
    if entry is None: return None
    own = metrics.token_pnl(ts, PX.get(mint))
    if own is None: return None
    sw_in = swaps_after(mint, entry); sw_out = swaps_after(mint, exit_t) if exit_t else None
    res = {"own_roi": own["roi"], "hold": (exit_t - entry) if exit_t else None}
    own_px = ts[0][3] / ts[0][2] / 1.03  # cüzdanın alış fiyatı, ücret/bahşiş payı çıkarılmış
    p1 = price(sw_in, entry + 1)
    res["jump"] = p1 / own_px - 1 if p1 else None  # alımdan 1 sn sonra fiyat ne kadar sıçramış (kopyacı baskısı)
    for d in DELAYS:
        pin = price(sw_in, entry + d)
        if not pin: res[d] = None; continue
        if exit_t:
            pout = price(sw_out, exit_t + d)
            if pout is None: pout = price(sw_out, exit_t + d + 15)  # sığ: biraz daha bekle
            if pout is None: res[d] = None; continue
        else:
            p = PX.get(mint); pout = p[0] if p and p[0] and (p[2] or 0) >= metrics.MIN_LIQ_USD else 0.0
        res[d] = (pout / pin) * (1 - FEE) ** 2 - 1
    return res

def wallet(w):
    out_path = os.path.join(HERE, "copysim", w + ".json")
    if os.path.exists(out_path): return json.load(open(out_path))
    d = json.load(open(os.path.join(HERE, "trades", w + ".json")))
    by = collections.defaultdict(list)
    for t, m, s, q, sol, sig, sg in d["rows"]: by[m].append((t, s, q, sol))
    items = sorted([(m, ts) for m, ts in by.items() if ts[0][0] >= SINCE], key=lambda x: -x[1][0][0])[:MAX_TOK]
    with ThreadPoolExecutor(6) as ex:
        sims = list(ex.map(lambda x: sim_token(*x), items))
    res = {m: s for (m, _), s in zip(items, sims) if s}
    os.makedirs(os.path.dirname(out_path), exist_ok=True); json.dump(res, open(out_path, "w"))
    return res

def summary(w, res):
    own = [r["own_roi"] for r in res.values()]
    line = f"{w[:8]} token {len(res):3} | cüzdanın kendisi: medyan {statistics.median(own):+6.1%}, kazanma %{100*sum(x>0 for x in own)/len(own):3.0f}"
    for d in DELAYS:
        v = [r[str(d)] if str(d) in r else r.get(d) for r in res.values()]; v = [x for x in v if x is not None]
        if v: line += f" | +{d}sn: n={len(v)} medyan {statistics.median(v):+6.1%} ort {statistics.mean(v):+6.1%} kazanma %{100*sum(x>0 for x in v)/len(v):3.0f}"
    j = [r["jump"] for r in res.values() if r.get("jump") is not None]
    if j: line += f" | 1sn sıçrama medyan {statistics.median(j):+.0%}"
    return line

if __name__ == "__main__":
    for w in sys.argv[1:]:
        r = wallet(w); print(summary(w, r), f"| çağrı {hl.CALLS['n']}", flush=True)
