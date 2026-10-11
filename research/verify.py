import json,hl,time
fl={o["wallet"]:o for o in json.load(open("flags.json"))}
A=[w for w in fl if fl[w]["early_in"] and list(fl[w]["early_in"][0][:3])==["baton",75,24]]
print("Cluster A:",len(A))
d=json.load(open("early/Hg5Ja55T5wESq4vyFoiVCMeHXtGyVA69X2UHq8hgpump.json"))
slot75=[r for r in d["rows"] if r["slot_off"]==75 and r["tok"]>0]
print("buys in baton slot+75:",len(slot75),"of which cluster:",sum(r["payer"] in A for r in slot75))
for r in slot75[:12]: print("  ",r["payer"][:10],round(-r["sol"],2),r["sig"][:20])
# second-hop funders of cluster A
def funder(w):
    r=hl.rpc("getTransactionsForAddress",[w,{"sortOrder":"asc","limit":10,"transactionDetails":"full","encoding":"jsonParsed","maxSupportedTransactionVersion":1}])
    for tx in (r or {}).get("data",[]):
        keys=[k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
        if w in keys:
            i=keys.index(w); m=tx["meta"]
            if m["postBalances"][i]>m["preBalances"][i] and keys[0]!=w: return keys[0], tx["blockTime"], (m["postBalances"][i]-m["preBalances"][i])/1e9
    return None,None,None
print("\nCluster A funding chains:")
for w in A:
    f1=fl[w]["funder"]; f2=funder(f1) if f1 else (None,)
    f3=funder(f2[0]) if f2[0] else (None,)
    print(" ",w[:8],"<-",(f1 or "-")[:8],"<-",(f2[0] or "-")[:8],"<-",(f3[0] or "-")[:8], time.strftime("%Y-%m-%d",time.gmtime(f2[1])) if f2[1] else "")
# shared funder 5tzFkiKs: exchange or private?
F=None
s=[]
span=(time.time()-s[-1]["blockTime"])/3600 if s else 0
print("\nshared funder",F,"sigs:",len(s),"span hours:",round(span,1))
print("calls",hl.CALLS["n"])
