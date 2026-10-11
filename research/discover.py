import json,urllib.request,time,urllib.parse
H={"User-Agent":"curl/8.5.0"}
def get(u):
    try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=30))
    except Exception as e: return None
words="pump cat dog inu pepe frog trump elon ai agent meme moon sol based coin baby cto wif hat bonk chad gm doge shib ape monkey bear bull tiger dragon king queen grok gpt chill retard bro fart wojak giga sigma cult god jesus satoshi bitcoin china japan anime girl mom dad punk degen".split()
seen={}
for w in words:
    d=get("https://api.dexscreener.com/latest/dex/search?q="+urllib.parse.quote(w))
    for p in (d or {}).get("pairs") or []:
        if p.get("chainId")!="solana": continue
        a=p["baseToken"]["address"]
        if a in seen: continue
        seen[a]=p
    time.sleep(0.25)
now=time.time()*1000; rows=[]
for a,p in seen.items():
    age=(now-(p.get("pairCreatedAt") or now))/864e5
    fdv=p.get("fdv") or 0
    rows.append(dict(addr=a,sym=p["baseToken"]["symbol"],dex=p.get("dexId"),age_d=round(age,1),fdv=fdv,vol24=(p.get("volume") or {}).get("h24",0)))
json.dump(rows,open("disc_all.json","w"))
old=set(l.split()[0] for l in open("winners.txt"))
sel=[r for r in rows if r["addr"].endswith("pump") and r["age_d"]<=30 and r["fdv"]>=500_000 and r["addr"] not in old]
sel.sort(key=lambda r:-r["fdv"])
print("solana tokens seen",len(rows),"| new winners",len(sel))
for r in sel: print(r)
open("winners2.txt","w").write("\n".join(f'{r["addr"]} {r["sym"].replace(" ","_")}' for r in sel))
