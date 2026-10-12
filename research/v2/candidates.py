"""Doğrulanmış kuralı en güncel döneme uygula → aday listesi (candidates.json).

Kural (analyze2/robust ile 2–12 Eki testinde doğrulandı): son ~11 günde ≥10 token, kâr/harcama oranı
yüksek, kâr birkaç tokene bağlı değil. Burada dönem = SINCE..şimdi, tüm önbellekteki cüzdanlar.
"""
import json, os, sys, glob, collections, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics
HERE = metrics.HERE
SINCE = 1790812800  # 2026-10-01 00:00 UTC
px = json.load(open(os.path.join(HERE, "prices.json")))["px"]
out = []
for f in glob.glob(os.path.join(HERE, "trades", "*.json")):
    d = json.load(open(f))
    if d["status"] in ("bot", "yogun"): continue
    by = collections.defaultdict(list)
    for t, m, s, q, sol, sig, sg in d["rows"]: by[m].append((t, s, q, sol))
    toks = []
    for m, ts in by.items():
        r = metrics.token_pnl(ts, px.get(m))
        if r and r["first"] >= SINCE: r["mint"] = m; toks.append(r)
    if len(toks) < 10: continue
    st = metrics.window_stats(toks, (d["fetched"] - SINCE) / 86400)
    roi = st["pnl"] / st["cost"] if st["cost"] else 0
    st.update(wallet=d["wallet"], roi=round(roi, 3), status=d["status"],
              last_age_h=round((d["fetched"] - d["newest"]) / 3600, 1) if d["newest"] else None,
              mints=[x["mint"] for x in toks])
    out.append(st)
out.sort(key=lambda r: -r["roi"])
n = len(out); th = out[int(0.05 * n)]["roi"]
cand = [r for r in out if r["roi"] >= max(th, 0.2) and r["pnl"] >= 5 and (r["top3_share"] or 9) <= 0.8 and (r["last_age_h"] or 999) <= 72]
json.dump(cand, open(os.path.join(HERE, "candidates.json"), "w"), indent=0)
print(f"≥10 tokenli cüzdan {n}, üst %5 eşiği getiri ≥{th:+.0%}, filtre sonrası aday {len(cand)}, farklı token {len({m for r in cand for m in r['mints']})}")
for r in cand[:60]:
    print(f"{r['wallet'][:8]} getiri {r['roi']:+6.0%} kâr {r['pnl']:+7.1f} SOL token {r['n']:3} kazanma %{100*r['win']:.0f} medyan_tutma {r['med_hold_s']}s medyan_alım {r['med_cost']} SOL top3 {r['top3_share']} son {r['last_age_h']}sa")
