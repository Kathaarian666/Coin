"""Tokenlerin güncel fiyatı (SOL/token), DexScreener'dan, önbellekli (prices.json).

Her token için en likit SOL veya USD karşılığı havuzun fiyatı alınır. DexScreener'da hiç
havuzu olmayan token None olarak kaydedilir (metrikte sıfır sayılır: ölü/rug).
"""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "prices.json")
WSOL = "So11111111111111111111111111111111111111112"

def _get(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:
            time.sleep(2 * (i + 1))
    return None

def sol_usd():
    d = _get(f"https://api.dexscreener.com/tokens/v1/solana/{WSOL}")
    best = max((p for p in d if p["baseToken"]["address"] == WSOL and p.get("priceUsd")),
               key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    return float(best["priceUsd"])

def load():
    return json.load(open(PATH)) if os.path.exists(PATH) else {"_meta": {}, "px": {}}

def update(mints, max_age=6 * 3600):
    db = load(); px = db["px"]; now = time.time()
    todo = [m for m in set(mints) if m not in px or now - px[m][1] > max_age]
    if not todo: return db
    su = sol_usd(); db["_meta"]["sol_usd"] = su
    for i in range(0, len(todo), 30):
        chunk = todo[i:i + 30]
        d = _get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk)) or []
        best = {}
        for p in d:
            b = p["baseToken"]["address"]
            if b not in chunk: continue
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if p["quoteToken"]["address"] == WSOL and p.get("priceNative"): v = float(p["priceNative"])
            elif p.get("priceUsd"): v = float(p["priceUsd"]) / su
            else: continue
            if b not in best or liq > best[b][1]: best[b] = (v, liq)
        for m in chunk:
            px[m] = [best[m][0] if m in best else None, int(now), best[m][1] if m in best else 0]
        time.sleep(0.22)  # DexScreener: dakikada 300 istek
        if (i // 30) % 100 == 0: print(f"fiyat {i + len(chunk)}/{len(todo)}", flush=True)
    json.dump(db, open(PATH, "w"), separators=(",", ":"))
    return db
