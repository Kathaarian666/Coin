import json,glob,collections,urllib.request,time
H={"User-Agent":"curl/8.5.0"}
cnt=collections.Counter()
for f in glob.glob("pnl/*.json")+glob.glob("ev/*.json"):
    d=json.load(open(f))
    ms=d["pos"].keys() if isinstance(d,dict) else {e["m"] for e in d}
    cnt.update(ms)
mints=[m for m,c in cnt.items() if m.endswith("pump")]
print("unique pump mints traded by profiled wallets:",len(mints))
old=set(l.split()[0] for l in open("winners.txt"))
rows=[]
for i in range(0,len(mints),30):
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request("https://api.dexscreener.com/tokens/v1/solana/"+",".join(mints[i:i+30]),headers=H),timeout=30))
    except Exception as e: print("err",e); time.sleep(2); continue
    best={}
    for p in d:
        a=p["baseToken"]["address"]
        if a not in best or (p.get("liquidity") or {}).get("usd",0)>(best[a].get("liquidity") or {}).get("usd",0): best[a]=p
    now=time.time()*1000
    for a,p in best.items():
        rows.append(dict(addr=a,sym=p["baseToken"]["symbol"],age_d=round((now-(p.get("pairCreatedAt") or now))/864e5,1),fdv=p.get("fdv") or 0,
                         vol24=(p.get("volume") or {}).get("h24",0),liq=(p.get("liquidity") or {}).get("usd",0)))
    time.sleep(0.3)
json.dump(rows,open("disc2.json","w"))
sel=[r for r in rows if r["age_d"]<=30 and r["fdv"]>=400_000 and r["liq"]>=30_000 and r["addr"] not in old]
sel.sort(key=lambda r:-r["fdv"])
print("priced",len(rows),"| new winners",len(sel))
for r in sel[:60]: print(r["sym"][:12].ljust(13),r["age_d"],int(r["fdv"]),int(r["vol24"]),int(r["liq"]))
open("winners2.txt","w").write("\n".join(f'{r["addr"]} {r["sym"].replace(" ","_")[:15]}' for r in sel[:40]))
