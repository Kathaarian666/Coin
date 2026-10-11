import json,urllib.request,time
toks=[t.strip() for t in open("cands.txt") if t.strip()]
toks=list(dict.fromkeys(toks))
out=[]
for i in range(0,len(toks),30):
    u="https://api.dexscreener.com/tokens/v1/solana/"+",".join(toks[i:i+30])
    out+=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"curl/8.5.0","Accept":"*/*"}),timeout=30)); time.sleep(1)
best={}
for p in out:
    a=p["baseToken"]["address"]
    if a not in toks: continue
    if a not in best or (p.get("liquidity",{}) or {}).get("usd",0)>(best[a].get("liquidity",{}) or {}).get("usd",0): best[a]=p
now=time.time()*1000; rows=[]
for a,p in best.items():
    age=(now-p.get("pairCreatedAt",now))/864e5
    rows.append(dict(addr=a,sym=p["baseToken"]["symbol"],dex=p["dexId"],age_d=round(age,1),fdv=p.get("fdv") or 0,vol24=(p.get("volume") or {}).get("h24",0),liq=(p.get("liquidity") or {}).get("usd",0)))
rows.sort(key=lambda r:-r["fdv"])
json.dump(rows,open("pairs.json","w"))
for r in rows: print(r)
