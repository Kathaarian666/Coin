"""Aday cüzdanların giriş zamanlaması: ilk alım, token oluşturulduktan kaç sn sonra? Yaratıcı mı?"""
import json, os, sys, glob, statistics, collections
HERE = os.path.dirname(os.path.abspath(__file__))
L = json.load(open(os.path.join(HERE, "launch.json")))
C = json.load(open(os.path.join(HERE, "candidates.json")))
def profile(w, mints=None):
    d = json.load(open(glob.glob(os.path.join(HERE, "trades", w + ".json"))[0]))
    first = {}
    for t, m, s, q, sol, sig, sg in d["rows"]:
        if s == "B" and m not in first and (mints is None or m in mints): first[m] = t
    offs = [first[m] - L[m][0] for m in first if m in L]
    creator = sum(1 for m in first if m in L and L[m][2] == w)
    if not offs: return None
    b = lambda lo, hi: sum(lo <= o < hi for o in offs) / len(offs)
    return dict(n=len(offs), creator=creator, med_off=statistics.median(offs),
                p0=b(-10**9, 1), p5=b(1, 5), p60=b(5, 60), p600=b(60, 600), plate=b(600, 10**12))
print(f"{'cüzdan':9} {'token':>5} {'yaratıcı':>8} {'medyan giriş':>12} | {'<1sn':>5} {'1-5sn':>5} {'5-60sn':>6} {'1-10dk':>6} {'>10dk':>5}")
for r in C:
    p = profile(r["wallet"], set(r["mints"]))
    if not p: continue
    print(f"{r['wallet'][:8]:9} {p['n']:5} {p['creator']:8} {p['med_off']:10.0f}sn | {p['p0']:5.0%} {p['p5']:5.0%} {p['p60']:6.0%} {p['p600']:6.0%} {p['plate']:5.0%}")
