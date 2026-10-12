"""Sağlamlık: (a) sadece gerçekleşmiş kâr (satılmayan = 0), (b) her cüzdanın test kârından en iyi token çıkarılmış."""
import json, os, sys, statistics, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prices, metrics
from analyze2 import SPLIT, EXCL, U, HERE, ds, px
def tokens(d, pxm):
    by = collections.defaultdict(list)
    for t, m, s, q, sol, sig, sg in d["rows"]:
        if m not in EXCL: by[m].append((t, s, q, sol))
    tr, te = [], []
    for m, ts in by.items():
        r = metrics.token_pnl(ts, pxm.get(m))
        if r: r["mint"] = m; (tr if r["first"] < SPLIT else te).append(r)
    return tr, te
rows = []
for d in ds:
    if d["status"] == "bot": continue
    tr, te = tokens(d, px); tr0, te0 = tokens(d, {})
    if len(tr) < 5: continue
    c = sum(x["cost"] for x in tr)
    rows.append(dict(w=d["wallet"], troi=sum(x["pnl"] for x in tr) / c if c else 0, n_te=len(te),
                     te=sum(x["pnl"] for x in te), te_real=sum(x["pnl"] for x in te0),
                     te_wo_best=sum(x["pnl"] for x in te) - max([x["pnl"] for x in te], default=0),
                     te_cost=sum(x["cost"] for x in te), best=max(te, key=lambda x: x["pnl"]) if te else None))
rows = [r for r in rows if r["n_te"] >= 3]
rows.sort(key=lambda r: -r["troi"])
def line(name, sel):
    c = sum(r["te_cost"] for r in sel)
    f = lambda k: f"%{100*sum(r[k]>0 for r in sel)/len(sel):3.0f} kârlı, {sum(r[k] for r in sel)/c:+6.1%}"
    print(f"{name:26} n={len(sel):4} | güncel fiyatla {f('te')} | sadece gerçekleşen {f('te_real')} | en iyi token hariç {f('te_wo_best')}")
n = len(rows)
for q, name in ((1, "hepsi"), (0.5, "eğitim getirisi üst %50"), (0.2, "üst %20"), (0.1, "üst %10"), (0.05, "üst %5")):
    line(name, rows[:int(n * q)])
line("alt %50 (karşılaştırma)", rows[n // 2:])
print("\nüst %5'te testteki en büyük tek token kazançları:")
for r in sorted(rows[:int(n * 0.05)], key=lambda r: -(r["best"]["pnl"] if r["best"] else 0))[:8]:
    b = r["best"]; print(f"  {r['w'][:8]} test {r['te']:+8.1f} SOL, en iyi token {b['mint'][:8]} {b['pnl']:+8.1f} SOL (maliyet {b['cost']:.1f}, elde kalan %{100*b['held_frac']:.0f})")
