import json,glob,collections,hl,time
from concurrent.futures import ThreadPoolExecutor
rows={r["wallet"]:r for r in json.load(open("proflow.json"))}
names={l.split()[0]:l.split()[1] for l in open("winners.txt")}
early=collections.defaultdict(dict); creators={}
for f in glob.glob("early/*.json"):
    d=json.load(open(f)); t=d["token"]; creators[d["creator"]]=names[t]
    for r in d["rows"]:
        if r["tok"]>0 and t not in early[r["payer"]]: early[r["payer"]][t]=(r["slot_off"],r["sec_off"],-r["sol"])
cand=[r for r in rows.values() if r["closed"]>=8 and r["realized_sol"]>=30]
print("candidates",len(cand))
def first_funder(w):
    r=hl.rpc("getTransactionsForAddress",[w,{"sortOrder":"asc","limit":10,"transactionDetails":"full","encoding":"jsonParsed","maxSupportedTransactionVersion":1}])
    if not r or not r.get("data"): return None,None
    for tx in r["data"]:
        keys=[k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
        if w not in keys: continue
        i=keys.index(w); m=tx["meta"]
        if m["postBalances"][i]-m["preBalances"][i]>0 and keys[0]!=w:
            return keys[0], tx["blockTime"]
    return None, r["data"][0]["blockTime"]
with ThreadPoolExecutor(6) as ex: ff=dict(zip([c["wallet"] for c in cand], ex.map(first_funder,[c["wallet"] for c in cand])))
out=[]
for c in cand:
    w=c["wallet"]; p=json.load(open(f"pnl/{w}.json"))["pos"]
    xfer=[m for m,v in p.items() if v["bq"]>0 and v["sq"]>1.2*v["bq"] and v["sout"]>1]
    e=early.get(w,{})
    fund,born=ff[w]
    out.append(dict(c, funder=fund, wallet_age_d=round((time.time()-born)/86400,1) if born else None,
        early_in=[(names[t],s[0],s[1],round(s[2],2)) for t,s in e.items()],
        first_slot_buys=sum(1 for s in e.values() if s[0]<=1),
        sold_more_than_bought=len(xfer), is_creator=creators.get(w)))
fc=collections.Counter(o["funder"] for o in out if o["funder"])
for o in out: o["shared_funder"]=fc.get(o["funder"],0) if o["funder"] else 0
json.dump(out,open("flags.json","w"),indent=1)
out.sort(key=lambda o:-o["realized_sol"])
for o in out:
    print(o["wallet"][:12], o["realized_sol"], "win",o["win_rate"], "closed",o["closed"], "tpd",o["tok_per_day"],"hold",o["med_hold_min"],"age",o["wallet_age_d"],"| funder",(o["funder"] or "-")[:8],"x"+str(o["shared_funder"]), "| slot<=1:",o["first_slot_buys"],"| xfer-sells:",o["sold_more_than_bought"],"|",o["early_in"][:3], o["is_creator"] or "")
print("calls",hl.CALLS["n"])
