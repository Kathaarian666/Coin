import json,glob,collections
names={l.split()[0]:l.split()[1] for l in open("winners.txt")}
by=collections.defaultdict(dict); creators={}
for f in glob.glob("early/*.json"):
    d=json.load(open(f)); t=d["token"]; creators[t]=d["creator"]
    last=max([r["sec_off"] for r in d["rows"]] or [0])
    print(names[t], "covered min:", round(last/60,1), "buyers:", len({r["payer"] for r in d["rows"] if r["tok"]>0}))
    for r in d["rows"]:
        if r["tok"]>0:
            e=by[r["payer"]].setdefault(t,dict(first_sec=r["sec_off"],first_slot=r["slot_off"],sol_in=0,sol_out=0,nb=0,ns=0))
            e["sol_in"]+= -r["sol"]; e["nb"]+=1
        else:
            if r["payer"] in by and t in by[r["payer"]]:
                e=by[r["payer"]][t]; e["sol_out"]+=r["sol"]; e["ns"]+=1
rep=[(w,v) for w,v in by.items() if len(v)>=2]
rep.sort(key=lambda x:-len(x[1]))
print("\nwallets early in >=2 winners:",len(rep), " >=3:",sum(len(v)>=3 for w,v in rep))
cs=set(creators.values())
for w,v in rep[:40]:
    print(w, len(v), "creator!" if w in cs else "", [ (names[t], e["first_sec"], round(e["sol_in"],2)) for t,e in v.items()])
json.dump({w:v for w,v in rep},open("repeat.json","w"))
