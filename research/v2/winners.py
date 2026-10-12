"""Son WINDOW_DAYS günde açılıp büyüyen Solana tokenlerini topla (winners.json).

Kaynaklar: GeckoTerminal (hacme göre ve trend havuzlar), Jupiter (trend / en çok işlem gören /
organik skor), DexScreener (boost listeleri). Her aday DexScreener'dan doğrulanır:
havuz açılışı 2–WINDOW_DAYS gün önce, en yüksek FDV >= MIN_FDV_USD.
"""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prices import _get, WSOL

HERE = os.path.dirname(os.path.abspath(__file__))
WINDOW_DAYS = 21
MIN_FDV_USD = 1_000_000
SKIP = {WSOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}

def gecko():
    out = set()
    urls = [f"https://api.geckoterminal.com/api/v2/networks/solana/pools?sort=h24_volume_usd_desc&page={p}" for p in range(1, 11)]
    urls += [f"https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?duration={d}&page={p}"
             for d in ("1h", "6h", "24h") for p in range(1, 6)]
    for u in urls:
        d = _get(u) or {}
        for p in d.get("data", []):
            for k in ("base_token",):
                tid = p["relationships"][k]["data"]["id"]
                out.add(tid.split("_", 1)[1])
        time.sleep(2.2)  # GeckoTerminal: dakikada 30 istek
    return out

def jupiter():
    out = set()
    for kind in ("toptrending", "toptraded", "toporganicscore"):
        for iv in ("1h", "6h", "24h"):
            d = _get(f"https://lite-api.jup.ag/tokens/v2/{kind}/{iv}?limit=100") or []
            out |= {x["id"] for x in d}
    return out

def dexscreener():
    out = set()
    for u in ("token-boosts/latest/v1", "token-boosts/top/v1", "token-profiles/latest/v1"):
        d = _get("https://api.dexscreener.com/" + u) or []
        out |= {x["tokenAddress"] for x in d if x.get("chainId") == "solana"}
    return out

def verify(cands):
    now = time.time(); keep = {}
    cands = [c for c in cands if c not in SKIP]
    for i in range(0, len(cands), 30):
        chunk = cands[i:i + 30]
        for p in _get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk)) or []:
            b = p["baseToken"]["address"]
            if b not in chunk: continue
            created = (p.get("pairCreatedAt") or 0) / 1000
            k = keep.setdefault(b, dict(mint=b, symbol=p["baseToken"]["symbol"], created=created or now, fdv=0, liq=0, vol24=0, dexes=set()))
            if created: k["created"] = min(k["created"], created)
            k["fdv"] = max(k["fdv"], p.get("fdv") or 0); k["liq"] += (p.get("liquidity") or {}).get("usd") or 0
            k["vol24"] += (p.get("volume") or {}).get("h24") or 0; k["dexes"].add(p["dexId"])
        time.sleep(0.22)
    res = []
    for k in keep.values():
        age = (now - k["created"]) / 86400
        k["age_d"] = round(age, 1); k["dexes"] = sorted(k["dexes"])
        if 2 <= age <= WINDOW_DAYS and k["fdv"] >= MIN_FDV_USD: res.append(k)
    return sorted(res, key=lambda k: -k["fdv"])

if __name__ == "__main__":
    c = set(); 
    for name, f in (("dexscreener", dexscreener), ("jupiter", jupiter), ("gecko", gecko)):
        s = f(); print(name, len(s), flush=True); c |= s
    res = verify(list(c))
    json.dump(res, open(os.path.join(HERE, "winners.json"), "w"), indent=0)
    print("aday", len(c), "→ son", WINDOW_DAYS, "günde açılmış, FDV >= 1M$:", len(res))
    for k in res[:40]: print(f"{k['symbol'][:12]:12} {k['fdv']/1e6:8.1f}M$ yaş {k['age_d']:5}g {','.join(k['dexes'])}")
