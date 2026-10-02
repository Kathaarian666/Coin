"""Life of every coin on Fomo, from its first Fomo trade (no trading rule, no target): buyers, sellers, peak multiple
over the first buy price (held on two buys in a row) and when, price at 1/6/24 h, life span, first-10-minute flow, FDV.

  python scripts/coin_lifecycle.py <trades.db> <out.parquet>
"""
import sqlite3, sys, numpy as np, pandas as pd
db=sqlite3.connect(sys.argv[1])
t=pd.read_sql("select ts,token,side,trader,usd,amount from trades",db)
sup=dict(db.execute("select n.id, s.raw from supply s join names n on n.addr=s.addr and n.kind='token'"))
t['px']=np.where((t.usd>0)&(t.amount>0),t.usd/t.amount,np.nan)
t=t.sort_values(['token','ts'])
END=t.ts.max()
rows=[]
for tok,g in t.groupby('token',sort=False):
    ts=g.ts.values; side=g.side.values; px=g.px.values; who=g.trader.values; usd=g.usd.fillna(0).values
    b=(side==1)&~np.isnan(px)
    if b.sum()<3: 
        rows.append((tok,ts[0],len(set(who[side==1])),0,np.nan,np.nan,np.nan,np.nan,np.nan,np.nan,0,ts[-1]-ts[0],usd[side==1].sum(),np.nan,np.nan)); continue
    bt,bp=ts[b],px[b]; p0=bp[0]; t0=ts[0]
    held=np.minimum(bp[:-1],bp[1:])/p0; k=held.argmax()
    def at(h):
        if t0+h*3600>END: return np.nan
        m=(bt>=t0+h*3600-600)&(bt<=t0+h*3600+600)
        if m.any(): return np.median(bp[m])/p0
        prev=bp[bt<t0+h*3600]
        if not len(prev): return np.nan
        return prev[-1]/p0*(0.5 if bt[-1]<t0+h*3600-1800 else 1)
    # buyers in first 10 min
    f10=set(who[(side==1)&(ts<t0+600)])
    rows.append((tok,t0,len(set(who[side==1])),len(set(who[side==0])),held[k],(bt[k+1]-t0)/60,at(1),at(6),at(24),
                 p0*sup[tok] if sup.get(tok) else np.nan,len(f10),ts[-1]-t0,usd[side==1].sum(),bp[-1]/p0/held[k] if held[k]>0 else np.nan,usd[(side==1)&(ts<t0+600)].sum()))
c=pd.DataFrame(rows,columns='tok t0 buyers sellers peak t_peak m1 m6 m24 fdv0 b10 life usd ret_from_peak usd10'.split())
c.to_parquet(sys.argv[2])
