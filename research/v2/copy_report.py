"""copysim sonuçlarını özetle: hangi cüzdanlar +1/+3 sn kopyada kârlı?"""
import json, os, glob, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
L = json.load(open(os.path.join(HERE, "launch.json")))
rows = []; allv = {"1": [], "3": [], "10": []}
for f in glob.glob(os.path.join(HERE, "copysim", "*.json")):
    w = os.path.basename(f)[:-5]; res = json.load(open(f))
    if not res: continue
    r = dict(w=w, n=len(res), own=statistics.median(x["own_roi"] for x in res.values()),
             creator=sum(1 for m in res if m in L and L[m][2] == w))
    for d in ("1", "3", "10"):
        v = [x[d] for x in res.values() if x.get(d) is not None]; allv[d] += v
        r[f"n{d}"] = len(v); r[f"med{d}"] = statistics.median(v) if v else None
        r[f"mean{d}"] = statistics.mean(v) if v else None; r[f"sum{d}"] = sum(v)
        r[f"win{d}"] = sum(x > 0 for x in v) / len(v) if v else None
    j = [x["jump"] for x in res.values() if x.get("jump") is not None]
    r["jump"] = statistics.median(j) if j else None
    rows.append(r)
print("tüm cüzdanlar birlikte (her işlem 1 birim):")
for d in ("1", "3", "10"):
    v = allv[d]; print(f"  +{d}sn: {len(v)} işlem, medyan {statistics.median(v):+.1%}, ortalama {statistics.mean(v):+.1%}, kazanma %{100*sum(x>0 for x in v)/len(v):.0f}")
ok = [r for r in rows if r["n1"] >= 8]
print(f"\n≥8 simüle işlemi olan {len(ok)} cüzdan; +1sn ortalamada pozitif: {sum(r['mean1']>0 for r in ok)}, medyanda pozitif: {sum(r['med1']>0 for r in ok)}")
print(f"+3sn ortalamada pozitif: {sum((r['mean3'] or -1)>0 for r in ok if r['n3']>=8)} / {sum(1 for r in ok if r['n3']>=8)}")
print("\nkopyada en iyi 15 (+1sn ortalamaya göre):")
for r in sorted(ok, key=lambda r: -r["mean1"])[:15]:
    f = lambda x: f"{x:+6.0%}" if x is not None else "   yok"
    print(f"  {r['w'][:8]} n={r['n1']:2} kendi medyan {f(r['own'])} | +1sn medyan {f(r['med1'])} ort {f(r['mean1'])} kazanma {f(r['win1'])} | +3sn ort {f(r['mean3'])} | 1sn sıçrama {f(r['jump'])} | yaratıcı {r['creator']}")
import math
print("\nsıçrama ile kopya getirisi ilişkisi:")
for lo, hi in ((-9, 0.02), (0.02, 0.10), (0.10, 0.25), (0.25, 99)):
    g = [r for r in ok if r["jump"] is not None and lo <= r["jump"] < hi]
    if g: print(f"  sıçrama {lo:+.0%}..{hi:+.0%}: {len(g):3} cüzdan, +1sn ort. getiri medyanı {statistics.median(r['mean1'] for r in g):+.1%}")
