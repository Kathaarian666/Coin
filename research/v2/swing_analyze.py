"""Uzun tutan havuzu: tutma süresi dağılımı ve eğitim→test kalıcılığı (havuz tokenleri testten hariç)."""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prices, metrics
HERE = prices.HERE
SPLIT = 1790899200
U = [l.strip() for l in open(os.path.join(HERE, "swing_wallets.txt")) if l.strip()]
EXCL = frozenset(k["mint"] for k in json.load(open(os.path.join(HERE, "swing_tokens.json"))))
ds = [json.load(open(p)) for w in U for p in [os.path.join(HERE, "trades", w + ".json")] if os.path.exists(p)]
px = prices.update({r[1] for d in ds for r in d["rows"]})["px"]
M = [metrics.wallet_metrics(d, px, SPLIT, EXCL) for d in ds]
import collections
print("durum:", dict(collections.Counter(m["status"] for m in M)))
ok = [m for m in M if m["status"] not in ("bot", "yogun")]
holds = collections.Counter()
for m in ok:
    h = m["train"].get("med_hold_s") if m["train"].get("n") else None
    holds["yok" if h is None else "<1dk" if h < 60 else "1-10dk" if h < 600 else "10-60dk" if h < 3600 else "1-24sa" if h < 86400 else ">1gün"] += 1
print("eğitim dönemi medyan tutma:", dict(holds))
def show(name, sel):
    te = [m for m in sel if m["test"].get("n", 0) >= 3]
    if not te: print(f"{name:44} seçilen {len(sel)}, testte yeterli işlem yok"); return
    p = [m["test"]["pnl"] for m in te]; c = sum(m["test"]["cost"] for m in te)
    print(f"{name:44} seçilen {len(sel):4} | testte ≥3 token {len(te):4} | kârlı %{100*sum(x>0 for x in p)/len(p):3.0f} | medyan {statistics.median(p):+6.2f} SOL | getiri {sum(p)/c:+.1%}")
T = lambda m: m["train"]
base = [m for m in ok if T(m).get("n", 0) >= 5]
show("eğitimde ≥5 token (taban)", base)
show("eğitimde zararlı", [m for m in base if T(m)["pnl"] < 0])
show("eğitimde kârlı", [m for m in base if T(m)["pnl"] > 0])
slow = [m for m in base if (T(m).get("med_hold_s") or 0) >= 600]
show("tutma ≥10 dk", slow)
show("tutma ≥10 dk ve eğitimde kârlı", [m for m in slow if T(m)["pnl"] > 0])
show("tutma ≥10 dk, kârlı, getiri ≥%20", [m for m in slow if T(m)["pnl"] > 0 and T(m)["pnl"] / T(m)["cost"] >= 0.2])
json.dump(M, open(os.path.join(HERE, "metrics_swing.json"), "w"), indent=0)
