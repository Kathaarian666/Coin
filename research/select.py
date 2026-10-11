import json, glob, collections, itertools, os
from pnl import summarize
names = {}
for f in ("winners.txt", "winners2.txt"):
    for l in open(f):
        a, s = l.split()[:2]; names[a] = s
early = collections.defaultdict(dict)
for f in glob.glob("early/*.json"):
    d = json.load(open(f)); t = d["token"]
    for r in d["rows"]:
        if r["tok"] > 0 and t not in early[r["payer"]]:
            early[r["payer"]][t] = (r["slot_off"], r["sec_off"], -r["sol"])
pool = set()
for f in ("lowfreq.txt", "lowfreq05.txt", "lowfreq_new.txt"):
    pool |= {l.strip() for l in open(f) if l.strip()}
rows = []
for w in pool:
    p = f"pnl/{w}.json"
    if os.path.exists(p): rows.append(summarize(json.load(open(p))))
print("profiled low-frequency wallets:", len(rows))
def ok(r):
    return (r["closed"] >= 15 and (r["win_rate"] or 0) >= 0.40 and r["realized_sol"] >= 15
            and r["top2_share"] is not None and r["top2_share"] <= 0.7 and (r["tok_per_day"] or 99) <= 15)
good = [r for r in rows if ok(r)]
print("pass consistency filter:", len(good))
# cluster: wallets entering the same tokens within 5s of each other
pos = {r["wallet"]: {m: v for m, v in json.load(open(f"pnl/{r['wallet']}.json"))["pos"].items() if v["bq"] > 0} for r in good}
parent = {w: w for w in pos}
def find(x):
    while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
    return x
for a, b in itertools.combinations(pos, 2):
    common = set(pos[a]) & set(pos[b])
    same = sum(1 for m in common if pos[a][m]["first"] and pos[b][m]["first"] and abs(pos[a][m]["first"] - pos[b][m]["first"]) <= 5)
    if same >= 5 and same >= 0.3 * min(len(pos[a]), len(pos[b])): parent[find(a)] = find(b)
clusters = collections.defaultdict(list)
for w in pos: clusters[find(w)].append(w)
out = []
for root, ws in clusters.items():
    rs = sorted([r for r in good if r["wallet"] in ws], key=lambda r: -r["realized_sol"])
    rep = dict(rs[0]); rep["cluster_size"] = len(ws); rep["cluster_sol"] = round(sum(r["realized_sol"] for r in rs), 1)
    rep["members"] = [r["wallet"] for r in rs]
    rep["early_in"] = [(names.get(t, t[:6]), s[1], round(s[2], 2)) for t, s in early.get(rep["wallet"], {}).items()]
    out.append(rep)
out.sort(key=lambda r: -r["realized_sol"])
json.dump(out, open("selected.json", "w"), indent=1)
print("unique operators after cluster merge:", len(out))
for r in out:
    print(r["wallet"][:10], r["realized_sol"], "win", r["win_rate"], "closed", r["closed"], "tpd", r["tok_per_day"],
          "hold", r["med_hold_min"], "top2", r["top2_share"], "days", r["days"], "| cluster", r["cluster_size"], r["early_in"][:2])
