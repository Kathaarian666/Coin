"""Ortak alım sinyali: k farklı 'yetenekli' operatör aynı tokeni W sn içinde ilk kez aldığında sinyal.
Yetenek sadece eğitim döneminde (SPLIT öncesi) ve sadece gerçekleşmiş kârla ölçülür (gelecek bilgisi sızmaz).
Test döneminde sinyalden +ENTRY_DELAY sn sonra havuz fiyatından giriş, HORIZONS sonra çıkış simüle edilir.
Kullanım: python3 consensus.py  → consensus.json + özet
"""
import json, os, sys, glob, collections, itertools, statistics, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics, copysim
HERE = metrics.HERE
SPLIT = 1790899200        # 2026-10-02
W = 600                   # sinyal penceresi (sn)
ENTRY_DELAY = 3
HORIZONS = (300, 1800, 7200, 86400)
FEE = 0.015
MAX_SIG = 400

def load():
    out = {}
    for f in glob.glob(os.path.join(HERE, "trades", "*.json")):
        d = json.load(open(f))
        if d["status"] in ("bot", "yogun") or d["oldest"] is None or d["oldest"] > SPLIT - 5 * 86400: continue
        out[d["wallet"]] = d
    return out

def train_stats(d):
    by = collections.defaultdict(list)
    for t, m, s, q, sol, sig, sg in d["rows"]:
        if t < SPLIT: by[m].append((t, s, q, sol))
    toks = [r for ts in by.values() for r in [metrics.token_pnl(ts, None)] if r and r["first"] < SPLIT - 86400]
    if len(toks) < 5: return None
    cost = sum(x["cost"] for x in toks); pnl = sum(x["pnl"] for x in toks)
    return dict(n=len(toks), pnl=pnl, roi=pnl / cost if cost else 0)

def first_buys(d, lo, hi):
    fb = {}
    for t, m, s, q, sol, sig, sg in d["rows"]:
        if s == "B" and lo <= t < hi and m not in fb: fb[m] = (t, sol)
    return fb

def clusters(ws, D):
    """Aynı tokenlere ≤5 sn arayla giren cüzdanlar tek operatör."""
    fb = {w: first_buys(D[w], 0, SPLIT) for w in ws}
    parent = {w: w for w in ws}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    inv = collections.defaultdict(list)
    for w in ws:
        for m, (t, _) in fb[w].items(): inv[m].append((t, w))
    pair = collections.Counter()
    for m, lst in inv.items():
        lst.sort()
        for (t1, a), (t2, b) in itertools.combinations(lst, 2):
            if t2 - t1 <= 5: pair[tuple(sorted((a, b)))] += 1
    for (a, b), c in pair.items():
        if c >= 5 and c >= 0.3 * min(len(fb[a]), len(fb[b])): parent[find(a)] = find(b)
    return {w: find(w) for w in ws}

def signals(group, D, k):
    """Test dönemindeki sinyaller: [(mint, sinyal_zamanı, operatörler)]"""
    ev = collections.defaultdict(list)
    for w, op in group.items():
        for m, (t, sol) in first_buys(D[w], SPLIT, 4e9).items():
            if sol >= 0.1: ev[m].append((t, op))
    out = []
    for m, lst in ev.items():
        lst.sort(); seen = {}
        for t, op in lst:
            seen = {o: tt for o, tt in seen.items() if t - tt <= W}
            seen.setdefault(op, t)
            if len(seen) >= k: out.append((m, t, sorted(seen))); break
    return out

def price_after(mint, t, wait=600):
    sw = copysim.swaps_after(mint, t)
    p = [x[1] for x in sw if t <= x[0] <= t + 15][:3]
    if not p: p = [x[1] for x in sw if t <= x[0] <= t + wait][:1]
    return statistics.median(p) if p else None

def simulate(sig):
    m, t, ops = sig
    pin = price_after(m, t + ENTRY_DELAY, 60)
    if not pin: return None
    r = {"mint": m, "t": t, "ops": len(ops)}
    px = json.load(open(os.path.join(HERE, "prices.json")))["px"].get(m)
    for h in HORIZONS:
        p = price_after(m, t + h)
        if p is None:  # o saatten sonra işlem yok: ölü sayılır (güncel fiyat varsa o)
            p = px[0] if px and px[0] and (px[2] or 0) >= metrics.MIN_LIQ_USD else 0.0
        r[h] = p / pin * (1 - FEE) ** 2 - 1
    return r

if __name__ == "__main__":
    D = load(); print("eğitim döneminde verisi olan cüzdan:", len(D))
    S = {w: s for w in D for s in [train_stats(D[w])] if s}
    rois = sorted(s["roi"] for s in S.values()); th = rois[int(0.9 * len(rois))]
    skilled = [w for w, s in S.items() if s["roi"] >= max(th, 0.1) and s["pnl"] >= 3]
    losers = [w for w, s in S.items() if s["roi"] < 0 and s["pnl"] < -3]
    print(f"≥5 tokenli {len(S)}, yetenekli (üst %10, getiri ≥{th:+.0%}, kâr ≥3) {len(skilled)}, zararlı (kontrol) {len(losers)}")
    res = {}
    for name, ws in (("yetenekli", skilled), ("zararli", losers)):
        g = clusters(ws, D); print(f"{name}: {len(ws)} cüzdan → {len(set(g.values()))} operatör")
        for k in (1, 2, 3):
            sigs = signals(g, D, k)
            if len(sigs) > MAX_SIG: sigs = random.Random(k).sample(sigs, MAX_SIG)  # kredi sınırı: rastgele örneklem
            sims = [r for r in map(simulate, sigs) if r]
            res[f"{name}_k{k}"] = sims
            line = f"  {name:9} k={k}: simüle edilen sinyal {len(sigs):4}, fiyatlı {len(sims):4}"
            for h in HORIZONS:
                v = [r[h] for r in sims]
                if v: line += f" | {h//60:>4}dk: medyan {statistics.median(v):+6.1%} ort {statistics.mean(v):+7.1%} kazanma %{100*sum(x>0 for x in v)/len(v):3.0f}"
            print(line, flush=True)
    json.dump(res, open(os.path.join(HERE, "consensus.json"), "w"))
