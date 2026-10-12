"""Eğitim döneminde seçilen cüzdanlar test döneminde de kârlı mı?"""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prices, metrics

ds = metrics.load_all()
mints = {r[1] for d in ds for r in d["rows"]}
px = prices.update(mints)["px"]
M = [metrics.wallet_metrics(d, px) for d in ds]
json.dump(M, open(os.path.join(prices.HERE, "metrics.json"), "w"), indent=0)
ok = [m for m in M if m["status"] != "bot"]
print(f"cüzdan {len(M)}, bot olmayan {len(ok)}, token {len(mints)}, fiyatı olan {sum(1 for m in mints if px[m][0])}")

def show(name, sel):
    te = [m for m in sel if m["test"]["n"] > 0]
    if not sel: print(name, "boş"); return
    p = [m["test"]["pnl"] for m in te]
    print(f"{name:42} seçilen {len(sel):4} | testte aktif {len(te):4} | testte kârlı %{100*sum(x>0 for x in p)/max(1,len(p)):3.0f}"
          f" | test medyan {statistics.median(p) if p else 0:+7.2f} SOL | toplam {sum(p):+8.1f} SOL"
          f" | medyan token getirisi {statistics.median([m['test']['med_roi'] for m in te]) if te else 0:+.1%}")

tr = lambda m: m["train"]
show("hepsi (bot hariç)", [m for m in ok if tr(m)["n"] > 0])
show("eğitimde kârlı", [m for m in ok if tr(m)["n"] >= 5 and tr(m)["pnl"] > 0])
show("eğitimde kârlı, ≥15 token, kazanma ≥%40", [m for m in ok if tr(m)["n"] >= 15 and tr(m)["pnl"] > 0 and tr(m)["win"] >= 0.4])
show(" + kâr top3'e bağlı değil (≤%70)", [m for m in ok if tr(m)["n"] >= 15 and tr(m)["pnl"] > 0 and tr(m)["win"] >= 0.4 and (tr(m)["top3_share"] or 9) <= 0.7])
show(" + medyan token getirisi > 0", [m for m in ok if tr(m)["n"] >= 15 and tr(m)["pnl"] > 0 and tr(m)["win"] >= 0.4 and (tr(m)["top3_share"] or 9) <= 0.7 and tr(m)["med_roi"] > 0])
show("eğitimde zararlı (karşılaştırma)", [m for m in ok if tr(m)["n"] >= 5 and tr(m)["pnl"] < 0])
