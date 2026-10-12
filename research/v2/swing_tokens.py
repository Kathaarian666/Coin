"""Uzun tutan (swing) cüzdan havuzu için yerleşik memecoinler → swing_tokens.json
Kaynak: Jupiter (en çok işlem gören / organik skor / trend) + GeckoTerminal (hacim, trend).
Süzgeç: havuz yaşı ≥ 3 gün, likidite ≥ 200k$, 24s işlem ≥ 1000, hacim ≥ 300k$, FDV 2M$–2B$, FDV/likidite ≤ 40.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prices import _get
from winners import gecko, jupiter, dexscreener, SKIP
HERE = os.path.dirname(os.path.abspath(__file__))
MAJORS = {"SOL", "WSOL", "USDC", "USDT", "JUP", "JTO", "PYTH", "RAY", "BONK", "WIF", "JLP", "MSOL", "JITOSOL", "BSOL",
          "ETH", "WETH", "BTC", "WBTC", "CBBTC", "TRUMP", "PUMP", "USD1", "PYUSD", "ORCA", "RENDER", "HNT", "W", "ZEC", "XRP"}
c = set()
for name, f in (("jupiter", jupiter), ("gecko", gecko), ("dexscreener", dexscreener)):
    s = f(); print(name, len(s), flush=True); c |= s
c = [m for m in c if m not in SKIP]; now = time.time(); keep = {}
for i in range(0, len(c), 30):
    chunk = c[i:i + 30]
    for p in _get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk)) or []:
        b = p["baseToken"]["address"]
        if b not in chunk: continue
        k = keep.setdefault(b, dict(mint=b, symbol=p["baseToken"]["symbol"], created=now, fdv=0, liq=0, vol=0, txns=0))
        if p.get("pairCreatedAt"): k["created"] = min(k["created"], p["pairCreatedAt"] / 1000)
        k["fdv"] = max(k["fdv"], p.get("fdv") or 0); k["liq"] += (p.get("liquidity") or {}).get("usd") or 0
        k["vol"] += (p.get("volume") or {}).get("h24") or 0
        tx = (p.get("txns") or {}).get("h24") or {}; k["txns"] += (tx.get("buys") or 0) + (tx.get("sells") or 0)
    time.sleep(0.21)
res = []
for k in keep.values():
    k["age_d"] = round((now - k["created"]) / 86400, 1)
    if (k["age_d"] >= 3 and k["liq"] >= 200_000 and k["txns"] >= 1000 and k["vol"] >= 300_000
            and 2e6 <= k["fdv"] <= 2e9 and k["fdv"] / k["liq"] <= 40 and k["symbol"].upper() not in MAJORS
            and k["symbol"].isascii()):
        res.append(k)
res.sort(key=lambda k: -k["vol"])
json.dump(res, open(os.path.join(HERE, "swing_tokens.json"), "w"), indent=0)
print(f"aday {len(c)} → süzgeç sonrası {len(res)}")
for k in res: print(f"  {k['symbol'][:12]:12} FDV {k['fdv']/1e6:7.1f}M$ lik {k['liq']/1e3:6.0f}k$ hacim {k['vol']/1e6:6.2f}M$ işlem {k['txns']:6} yaş {k['age_d']:6}g")
