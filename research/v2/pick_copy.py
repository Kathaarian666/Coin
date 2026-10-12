"""Kopya simülasyonu için aday: 1 dk'dan uzun tutan, getirisi >%10, kâr ≥3 SOL; yaratıcı olanlar sonra elenir."""
import json, os, sys, glob, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics
SINCE = 1790812800
px = json.load(open(os.path.join(metrics.HERE, "prices.json")))["px"]
out = []
for f in glob.glob(os.path.join(metrics.HERE, "trades", "*.json")):
    d = json.load(open(f))
    if d["status"] in ("bot", "yogun"): continue
    by = collections.defaultdict(list)
    for t, m, s, q, sol, sig, sg in d["rows"]: by[m].append((t, s, q, sol))
    toks = [r for m, ts in by.items() for r in [metrics.token_pnl(ts, px.get(m))] if r and r["first"] >= SINCE]
    if len(toks) < 8: continue
    st = metrics.window_stats(toks, 11); roi = st["pnl"] / st["cost"] if st["cost"] else 0
    if (st["med_hold_s"] or 0) >= 60 and roi > 0.1 and st["pnl"] >= 3:
        out.append((roi, d["wallet"]))
out.sort(reverse=True)
open(os.path.join(metrics.HERE, "copy_pick.txt"), "w").write("\n".join(w for _, w in out) + "\n")
print(len(out))
