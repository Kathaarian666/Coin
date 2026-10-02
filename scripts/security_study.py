"""Security criteria study (PROJE.md step 1): which checks flag the coins that turn out to be traps?

  python scripts/security_study.py <trades.db> <out.parquet> [<first day of new coins>=2026-09-18]
  python scripts/security_study.py report <out.parquet>

Moment: every new coin's 3rd distinct Fomo buyer (the alert moment the research used). Price there = the last
buy price. Everything after that moment is only used for the labels:
- hit2x: two buys in a row at >= 2x the moment's price, any time until the data ends (obs_h = hours observed)
- rug: before any 2x, within 60 min, two trades in a row (buys or sells) at <= 0.1x
- unsellable: in the next 24 h at least 5 new Fomo buyers and not a single Fomo sell
- quiet: no Fomo trade at all in the next 24 h
- trap = rug or unsellable (the user's definition, PROJE.md §1)
Checks known at the moment: Pons launch, Fomo sellers so far, Fomo churn (rhscanner.checks.wash), launcher
history (launches table, scripts/pons_launches.py), and contract facts read from the chain now (bytecode does
not change): size, function-set fingerprint (template), risky admin functions, EIP-1967 proxy, owner().
Contract facts are cached in the DB table `contracts`; clones are read through to their implementation.
"""

import json
import re
import sqlite3
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rhscanner.checks.contract import EIP1967_BEACON_SLOT, EIP1967_IMPL_SLOT, find_risky_functions  # noqa: E402

URLS = ["https://rpc.mainnet.chain.robinhood.com", "https://robinhood.drpc.org"]
CHUNK = 10  # coins per batch request (4 calls each); bigger batches get 429 every time
K = 3
START = pd.Timestamp("2026-09-18 00:00").value / 1e9  # one day after the data restarts: coins seen first are new
TRAP_OBS = 24 * 3600
RUG_WINDOW = 3600
OWNER = "0x8da5cb5b"
ZERO_OWNERS = {"0x" + "0" * 40, "0x000000000000000000000000000000000000dead"}


def rpc_batch(calls, urls=URLS):
    body = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    for attempt in range(10):
        try:
            req = urllib.request.Request(urls[attempt % len(urls)], json.dumps(body).encode(),
                                         {"content-type": "application/json", "user-agent": "Mozilla/5.0"})
            out = json.load(urllib.request.urlopen(req, timeout=60))
            res = {r["id"]: r.get("result") for r in out}
            return [res.get(i) for i in range(len(calls))]
        except Exception as exc:  # 429s and timeouts: wait and retry
            print("retry", exc, flush=True)
            time.sleep(2 + 3 * attempt)
    raise RuntimeError("RPC refused")


def rpc_many(calls, size=40, urls=URLS):
    out = []
    for n in range(0, len(calls), size):
        out += rpc_batch(calls[n:n + size], urls)
    return out


def selectors(code: str) -> str:
    """The contract's function set: PUSH4 operands in the dispatcher, sorted. Same template = same set."""
    b = bytes.fromhex(code[2:])
    found, i = set(), 0
    while i < len(b):
        op = b[i]
        if op == 0x63 and i + 4 < len(b):
            found.add(b[i + 1:i + 5].hex())
        i += 1 + (op - 0x5f if 0x60 <= op <= 0x7f else 0)
    return ",".join(sorted(found))


def contract_facts(db, tokens):
    db.execute("""CREATE TABLE IF NOT EXISTS contracts (token TEXT PRIMARY KEY, size INTEGER, fp TEXT, risky TEXT,
                  proxy INTEGER, owner TEXT)""")
    done = {r[0] for r in db.execute("SELECT token FROM contracts")}
    todo = [t for t in tokens if t not in done]
    print(f"kontrat: {len(todo)} coin okunacak", flush=True)
    for n in range(0, len(todo), CHUNK):
        part = todo[n:n + CHUNK]
        calls = []
        for t in part:
            calls += [("eth_getCode", [t, "latest"]), ("eth_getStorageAt", [t, EIP1967_IMPL_SLOT, "latest"]),
                      ("eth_getStorageAt", [t, EIP1967_BEACON_SLOT, "latest"]),
                      ("eth_call", [{"to": t, "data": OWNER}, "latest"])]
        res = rpc_batch(calls)
        rows = []
        for j, t in enumerate(part):
            code, impl, beacon, owner = res[4 * j:4 * j + 4]
            code = code or "0x"
            proxy = int(any(v and int(v, 16) for v in (impl, beacon)))
            own = "0x" + owner[-40:] if owner and len(owner) >= 66 else None
            rows.append((t, (len(code) - 2) // 2, selectors(code), ",".join(sorted(find_risky_functions(code))),
                         proxy, own))
        db.executemany("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?)", rows)
        db.commit()
        if n % 500 == 0:
            print(f"  {n + len(part)}/{len(todo)}", flush=True)
    return pd.read_sql("SELECT * FROM contracts", db).set_index("token")


CLONE = re.compile(r"73([0-9a-f]{40})5af4")  # minimal proxies (EIP-1167 and the shorter PUSH0 variant)


def resolve_clones(db):
    """Clones hold no logic of their own: read the implementation's code for the function set and risky functions."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(contracts)")]
    if "impl" not in cols:
        db.execute("ALTER TABLE contracts ADD COLUMN impl TEXT")
    todo = db.execute("SELECT token FROM contracts WHERE size <= 60 AND impl IS NULL").fetchall()
    if not todo:
        return
    codes = rpc_many([("eth_getCode", [t, "latest"]) for (t,) in todo])
    impl_of = {}
    for (t,), code in zip(todo, codes):
        m = CLONE.search((code or "").lower())
        impl_of[t] = "0x" + m.group(1) if m else ""
    impls = sorted({i for i in impl_of.values() if i})
    impl_code = dict(zip(impls, rpc_many([("eth_getCode", [i, "latest"]) for i in impls]) if impls else []))
    print(f"klon: {len(todo)} coin, {len(impls)} farklı asıl kontrat", flush=True)
    for t, i in impl_of.items():
        code = impl_code.get(i) or "0x"
        if i:
            db.execute("UPDATE contracts SET impl=?, fp=?, risky=? WHERE token=?",
                       (i, "clone:" + selectors(code), ",".join(sorted(find_risky_functions(code))), t))
        else:
            db.execute("UPDATE contracts SET impl='' WHERE token=?", (t,))
    db.commit()


def two_in_row(px, cond):
    ok = cond(px)
    hit = ok[:-1] & ok[1:]
    idx = np.flatnonzero(hit)
    return idx[0] if len(idx) else None


def flags(df):
    owner = df.owner.fillna("")
    out = {
        "Pons lansmanı": df.pons,
        "Pons değil": ~df.pons,
        "Fomo'da 2+ satıcı (satılabiliyor)": df.fomo_sellers >= 2,
        "Fomo'da hiç satış yok": df.fomo_sellers == 0,
        "Fomo churn >= %40": df.churn30 >= 0.4,
        "Geliştirici 3+ coin (21 gün)": df.launcher_prior >= 3,
        "Geliştirici 10+ coin (21 gün)": df.launcher_prior >= 10,
        "Şablon kontrat (aynı fonksiyon seti 50+ coinde)": df.template_n >= 50,
        "Nadir kontrat (aynı set < 5 coinde)": df.template_n < 5,
        "Proxy (yükseltilebilir)": df.proxy == 1,
        "Sahibi var (owner() dolu)": (owner != "") & ~owner.isin(ZERO_OWNERS),
        "Sahiplik devredilmiş": owner.isin(ZERO_OWNERS),
        "owner() fonksiyonu yok": owner == "",
    }
    for grp in ("mint", "blacklist", "fees", "pause", "limits", "trading", "upgrade"):
        out[f"Fonksiyon: {grp}"] = df.risky.fillna("").str.split(",").apply(lambda xs, g=grp: g in xs)
    if "top10_pct" in df:  # scripts/security_extra.py; NaN (not measured) counts as not flagged, see coverage
        out.update({
            "İlk 10 cüzdan > %30": df.top10_pct > 30,
            "İlk 10 cüzdan > %50": df.top10_pct > 50,
            "Tek cüzdan > %15": df.largest_pct > 15,
            "Geliştirici > %5": df.dev_pct > 5,
            "Geliştirici > %10": df.dev_pct > 10,
            "Geliştirici ilk aldığının yarısını sattı": df.dev_sold == True,  # noqa: E712
            "Bundle > %10": df.bundle_pct > 10,
            "Sniper > %10": df.sniper_pct > 10,
            "Sniper > %25": df.sniper_pct > 25,
            "Likidite < $1k (Fomo fiyat etkisinden)": 2 * df.depth_usd < 1000,
            "Likidite < $5k": 2 * df.depth_usd < 5000,
            "Hook yok": df.hook == "0x" + "0" * 40,
            "Hook: Pons": df.hook_named,
            "Hook: başka (Pons değil)": df.hook.str.startswith("0x") & (df.hook != "0x" + "0" * 40) & ~df.hook_named,
            "Hook nadir (< 40 coinde)": df.hook.str.startswith("0x") & (df.hook != "0x" + "0" * 40) & (df.hook_coins < 40),
            "Hook yükseltilebilir": df.hook_upgradeable,
        })
    return out


def report(path):
    df = pd.read_parquet(path)
    df = df[df.obs_h >= TRAP_OBS / 3600]
    pct = lambda m: f"%{100 * m.mean():.1f}" if len(m) else "-"  # noqa: E731
    print(f"{len(df)} coin (en az 24 saat izlenmiş), 3. Fomo alıcısı anı")
    print(f"tuzak {pct(df.trap)} (rug {pct(df.rug)}, satılamayan {pct(df.unsellable)}) · sessiz {pct(df.quiet)} · "
          f"2x {pct(df.hit2x)}\n")
    if "top10_pct" in df:
        print(f"ölçülebilen: holder {df.top10_pct.notna().sum()} · geliştirici {df.dev_pct.notna().sum()} · "
              f"bundle/sniper {df.sniper_pct.notna().sum()} · likidite {df.depth_usd.notna().sum()} · "
              f"hook bulunan {(df.hook != '').sum()} / {len(df)}\n")
    print(f"{'kontrol':48} {'coin':>6} {'pay':>6} {'tuzak':>7} {'diğer':>7} {'2x':>7} {'diğer':>7}")
    for name, m in flags(df).items():
        m = m.fillna(False).astype(bool)
        print(f"{name:48} {m.sum():6d} {pct(m):>6} {pct(df.trap[m]):>7} {pct(df.trap[~m]):>7} "
              f"{pct(df.hit2x[m]):>7} {pct(df.hit2x[~m]):>7}")


def main():
    if sys.argv[1] == "report":
        return report(sys.argv[2])
    global START
    db_path, out = sys.argv[1], sys.argv[2]
    if len(sys.argv) > 3:  # with the 3-17 Sep hole filled the data runs from 1 Sep: new coins from ~3 Sep
        START = pd.Timestamp(sys.argv[3]).value / 1e9
    db = sqlite3.connect(db_path, timeout=60)
    names = {i: a.lower() for i, a in db.execute("SELECT id, addr FROM names")}
    tr = pd.read_sql("SELECT ts, token, side, trader, usd, amount FROM trades ORDER BY token, ts", db)
    data_end = tr.ts.max()
    launches = {t: (ts, l) for t, ts, l in db.execute("SELECT lower(token), ts, lower(launcher) FROM launches")}
    by_launcher = defaultdict(list)
    for ts, l in launches.values():
        by_launcher[l].append(ts)
    for v in by_launcher.values():
        v.sort()

    rows = []
    for tok, g in tr.groupby("token", sort=False):
        if g.ts.iloc[0] < START:
            continue
        ts, side, trader = g.ts.values, g.side.values, g.trader.values
        px = np.where(g.amount.values > 0, g.usd.values / np.maximum(g.amount.values, 1e-30), np.nan)
        seen, i0 = set(), None
        for i in range(len(g)):
            if side[i] == 1:
                seen.add(trader[i])
                if len(seen) == K:
                    i0 = i
                    break
        if i0 is None:
            continue
        t0 = ts[i0]
        pre_buys = px[:i0 + 1][(side[:i0 + 1] == 1) & np.isfinite(px[:i0 + 1])]
        if not len(pre_buys):
            continue
        p0 = float(pre_buys[-1])  # the last price, as the alert shows it
        after = slice(i0 + 1, None)
        a_ts, a_side, a_px, a_tr = ts[after], side[after], px[after], trader[after]
        bmask = (a_side == 1) & np.isfinite(a_px)
        j = two_in_row(a_px[bmask], lambda p: p >= 2 * p0)
        t_hit = a_ts[bmask][j] if j is not None else None
        fin = np.isfinite(a_px)
        lim = (a_ts < t0 + RUG_WINDOW) & fin
        if t_hit is not None:
            lim &= a_ts < t_hit
        rug = two_in_row(a_px[lim], lambda p: p <= 0.1 * p0) is not None
        in24 = a_ts < t0 + TRAP_OBS
        new_buyers = len(set(a_tr[in24 & (a_side == 1)]) - seen)
        sells24 = int((in24 & (a_side == 0)).sum())
        # checks known at the moment
        pre = slice(0, i0 + 1)
        w30 = ts[pre] >= t0 - 1800
        b30, s30 = defaultdict(int), defaultdict(int)
        usd30 = g.usd.values[pre][w30]
        for s_, w_ in zip(side[pre][w30], trader[pre][w30]):
            (b30 if s_ == 1 else s30)[w_] += 1
        churners = {w for w in b30 if b30[w] >= 2 and s30[w] >= 2}
        tot = np.nansum(usd30)
        churn = float(np.nansum(usd30[np.isin(trader[pre][w30], list(churners))]) / tot) if tot else 0.0
        addr = names[tok]
        launch = launches.get(addr)
        prior = 0
        if launch:
            lt = by_launcher[launch[1]]
            prior = int(np.searchsorted(lt, launch[0]) - np.searchsorted(lt, launch[0] - 21 * 86400))
        rows.append(dict(
            token=addr, t0=t0, p0=p0, obs_h=(data_end - t0) / 3600,
            hit2x=t_hit is not None, rug=rug, unsellable=new_buyers >= 5 and sells24 == 0,
            quiet=int(in24.sum()) == 0, pons=launch is not None,
            launch_age_min=(t0 - launch[0]) / 60 if launch else np.nan,
            fomo_sellers=len(set(trader[pre][side[pre] == 0])), churn30=churn, launcher_prior=prior,
        ))
    df = pd.DataFrame(rows)
    print(f"{len(df)} coin (3. alıcı anı)", flush=True)
    facts = contract_facts(db, df.token.tolist())
    resolve_clones(db)
    facts = pd.read_sql("SELECT * FROM contracts", db).set_index("token")
    df = df.join(facts, on="token")
    fp_count = df.groupby("fp").token.transform("count")
    df["template_n"] = fp_count
    df["trap"] = df.rug | df.unsellable
    df.to_parquet(out, index=False)
    print("yazıldı", out)


if __name__ == "__main__":
    main()
