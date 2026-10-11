import json,sys,time,hl,os
from concurrent.futures import ThreadPoolExecutor
now=time.time()
def f(w):
    r=hl.rpc("getSignaturesForAddress",[w,{"limit":1000}])
    if r is None: return dict(w=w,err=1)
    n30=sum(1 for x in r if x.get("blockTime") and x["blockTime"]>now-30*86400)
    span=(now-r[-1]["blockTime"])/86400 if r and r[-1].get("blockTime") else 0
    return dict(w=w,n=len(r),n30=n30,span_d=round(span,1),oldest=r[-1].get("blockTime") if r else None)
ws=[l.strip() for l in open(sys.argv[1]) if l.strip()]
with ThreadPoolExecutor(6) as ex: res=list(ex.map(f,ws))
json.dump(res,open(sys.argv[2],"w"))
print("calls",hl.CALLS["n"])
