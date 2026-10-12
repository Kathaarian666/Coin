"""Mezun tokenlerden hayatta kalan büyükler: güncel FDV >= MIN_FDV ve likidite >= MIN_LIQ → survivors.json"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prices import _get
HERE = os.path.dirname(os.path.abspath(__file__))
MIN_FDV, MIN_LIQ = 2_000_000, 100_000
g = json.load(open(os.path.join(HERE, "grads.json")))
mints = [m for m, t in g.items() if t < time.time() - 2 * 86400]  # en az 2 gün önce mezun
keep = {}
for i in range(0, len(mints), 30):
    chunk = mints[i:i + 30]
    for p in _get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk)) or []:
        b = p["baseToken"]["address"]
        if b not in chunk: continue
        k = keep.setdefault(b, dict(mint=b, symbol=p["baseToken"]["symbol"], fdv=0, liq=0, vol=0, txns=0, grad=g[b]))
        k["fdv"] = max(k["fdv"], p.get("fdv") or 0); k["liq"] += (p.get("liquidity") or {}).get("usd") or 0
        k["vol"] += (p.get("volume") or {}).get("h24") or 0
        tx = (p.get("txns") or {}).get("h24") or {}; k["txns"] += (tx.get("buys") or 0) + (tx.get("sells") or 0)
    time.sleep(0.21)
ok = [k for k in keep.values() if k["fdv"] >= MIN_FDV and k["liq"] >= MIN_LIQ and k["txns"] >= 1000
      and k["vol"] >= 200_000 and k["fdv"] / k["liq"] <= 40 and k["symbol"].isascii()]
best = {}
for k in ok:  # aynı sembolden sadece hacmi en yüksek olan (taklitler elenir)
    s_ = k["symbol"].upper().replace(" ", "")
    if s_ not in best or k["vol"] > best[s_]["vol"]: best[s_] = k
res = sorted(best.values(), key=lambda k: -k["fdv"])
json.dump(list(keep.values()), open(os.path.join(HERE, "grads_dex.json"), "w"))
json.dump(res, open(os.path.join(HERE, "survivors.json"), "w"), indent=0)
print(f"mezun {len(mints)}, DexScreener'da {len(keep)}, süzgeç sonrası (sahteler ve taklitler elendi): {len(res)}")
for k in res[:40]: print(f"  {k['symbol'][:12]:12} FDV {k['fdv']/1e6:6.1f}M$ likidite {k['liq']/1e3:6.0f}k$ hacim24 {k['vol']/1e3:7.0f}k$ işlem24 {k['txns']:6} mezuniyet {time.strftime('%m-%d', time.gmtime(k['grad']))}")
