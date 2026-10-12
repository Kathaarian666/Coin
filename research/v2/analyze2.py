"""Bias'sız kalıcılık testi: havuz = 30 Eylül öncesi kazananların erken alıcıları (kâra bakılmadan),
seçim = 21 Eyl–2 Eki işlemleri, test = 2–12 Eki işlemleri (havuz tokenleri hariç)."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prices, metrics
HERE = prices.HERE
SPLIT = 1790899200  # 2026-10-02 00:00 UTC
U = [l.strip() for l in open(os.path.join(HERE, "universe.txt")) if l.strip()]
EXCL = frozenset(l.strip() for l in open(os.path.join(HERE, "universe_tokens.txt")) if l.strip())
ds = [json.load(open(os.path.join(HERE, "trades", w + ".json"))) for w in U if os.path.exists(os.path.join(HERE, "trades", w + ".json"))]
px = prices.update({r[1] for d in ds for r in d["rows"]})["px"]
M = [metrics.wallet_metrics(d, px, SPLIT, EXCL) for d in ds]
json.dump(M, open(os.path.join(HERE, "metrics_universe.json"), "w"), indent=0)
ok = [m for m in M if m["status"] != "bot"]
print(f"havuz {len(U)}, çekilen {len(ds)}, bot {len(M)-len(ok)}, sınır {sum(m['status']=='sinir' for m in M)}")

def show(name, sel):
    te = [m for m in sel if m["test"]["n"] >= 3]
    if not sel: print(f"{name:46} boş"); return
    p = [m["test"]["pnl"] for m in te]; c = sum(m["test"]["cost"] for m in te)
    print(f"{name:46} seçilen {len(sel):4} | testte ≥3 token {len(te):4} | testte kârlı %{100*sum(x>0 for x in p)/max(1,len(p)):3.0f}"
          f" | medyan {statistics.median(p) if p else 0:+6.2f} SOL | toplam {sum(p):+8.1f} SOL / {c:7.0f} SOL harcama = {sum(p)/c if c else 0:+.1%}")
T = lambda m: m["train"]
base = [m for m in ok if T(m)["n"] >= 5]
show("eğitimde ≥5 token (taban)", base)
show("eğitimde zararlı", [m for m in base if T(m)["pnl"] < 0])
show("eğitimde kârlı", [m for m in base if T(m)["pnl"] > 0])
show("eğitimde kârlı, ≥15 token, kazanma ≥%40", [m for m in base if T(m)["n"] >= 15 and T(m)["pnl"] > 0 and T(m)["win"] >= 0.4])
s4 = [m for m in base if T(m)["n"] >= 15 and T(m)["pnl"] > 0 and T(m)["win"] >= 0.4 and (T(m)["top3_share"] or 9) <= 0.7]
show(" + kâr top3'e bağlı değil", s4)
show(" + medyan token getirisi > 0", [m for m in s4 if T(m)["med_roi"] > 0])
show(" + kâr faktörü ≥ 1.5", [m for m in s4 if (T(m)["pf"] or 0) >= 1.5])
for q in (0.5, 0.8, 0.9, 0.95):
    roi = sorted(T(m)["pnl"] / T(m)["cost"] for m in base if T(m)["cost"] > 0)
    th = roi[int(q * len(roi))]
    show(f"eğitim getirisi (kâr/harcama) üst %{100-100*q:.0f} (≥{th:+.0%})", [m for m in base if T(m)["cost"] > 0 and T(m)["pnl"] / T(m)["cost"] >= th])
