import json
rows=json.load(open("disc2.json")); old=set(l.split()[0] for l in open("winners.txt"))
sel=[r for r in rows if r["addr"] not in old and r["fdv"]>=400_000 and r["liq"]>=30_000 and r["age_d"]<=30 and not (r["age_d"]<1.5 and r["fdv"]>3_000_000)]
sel.sort(key=lambda r:-r["fdv"])
for r in sel: print(r["sym"][:12].ljust(13),r["age_d"],int(r["fdv"]),int(r["vol24"]),int(r["liq"]),r["addr"])
open("winners2.txt","w").write("\n".join(r["addr"]+" "+r["sym"].replace(" ","_")[:15] for r in sel))
f=json.load(open("freq05.json")); ok=[x for x in f if not x.get("err")]
low=[x for x in ok if x["n"]<1000 or x["span_d"]>=15]
print("freq05 checked",len(ok),"low-freq",len(low))
open("lowfreq05.txt","w").write("\n".join(x["w"] for x in low))
