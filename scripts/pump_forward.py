"""Daily forward test of the frozen pump.fun volume-burst rule (PROJE.md §4.5e; user, 10 Oct: "a" - every day, a short
report). The rule was found on 3-8 Oct and is never changed here: every later day is data it has not seen.

  python scripts/pump_forward.py <veri folder> <work folder> <day YYYY-MM-DD> [<day> ...]

Steps: the `veri` branch's solana/ days into <work>/sol.db (scripts/solana_import.py, new days only) -> the graduations
Fomo saw that day, as in the research (the coin's first Fomo trade on a SOL-quoted PumpSwap pool, for a coin seen on
its bonding curve or whose pool was created after the data starts) -> pump.fun one-minute candles, GeckoTerminal for
a coin whose candles do not reach back to its graduation (scripts/pump_fetch.py; cached in <work>) -> the minutes after
each graduation (scripts/pump_lab.py grad_coin, 1- and 2-minute delay) -> the rule -> one row per day in
research/pump_forward.csv and a short Turkish report.
Rule (frozen 9 Oct): from 1 minute to 3 hours after the graduation, market cap >= $300k, $ volume of the last 5 minutes
>= $100k and price >= 1.1x of 5 minutes before -> buy a minute later, sell 5 minutes later (or at 1.5x / -15 %, a
minute after the minute that reaches it); only each coin's first signal. Net with costs at $100 and $300.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pump_fetch  # noqa: E402
from pump_lab import GRAD_RULES, grad_coin, grad_net, load  # noqa: E402

RULE = "tp1.5_sl0.15_h0.0833333"
VOL5, RET5, MCAP, MIN_AFTER = 1e5, 1.1, 3e5, 1
STAKES = (100, 300)
OUT = Path(__file__).resolve().parent.parent / "research" / "pump_forward.csv"
FIRST_FORWARD_DAY = "2026-10-09"  # 3-8 Oct is where the rule was found


def graduations(work: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Every graduation Fomo saw (ts) and each coin's busiest SOL-quoted PumpSwap pool."""
    import sqlite3
    t = load(str(work / "sol.db"))
    created = pd.read_sql("SELECT base, created_ts FROM pools", sqlite3.connect(work / "sol.db"))
    created = created.dropna().groupby("base").created_ts.min()
    swap = t[t.venue == 2]
    first = swap.groupby("mint").ts.min()
    had_curve = set(t.mint[t.venue == 1])
    new_pool = first.index.map(lambda m: created.get(m, -1) > t.ts.min()).to_numpy(bool)
    grads = first[first.index.isin(had_curve) | new_pool].to_frame("ts")
    main_pool = swap.groupby(["mint", "pool"]).size().reset_index().sort_values(0).drop_duplicates("mint", keep="last")
    return grads, main_pool.set_index("mint")["pool"]


def cached(path: Path) -> dict:
    return {(x := json.loads(line))["mint"]: x["candles"] for line in path.open()} if path.exists() else {}


def candles_for(day_grads: pd.DataFrame, pools: pd.Series, work: Path) -> dict:
    pump_path, gecko_path = work / "candles.jsonl", work / "gecko.jsonl"
    have = cached(pump_path)
    with pump_path.open("a") as f:
        for mint in day_grads.index:
            if mint not in have:
                have[mint] = (x := pump_fetch.candles(mint))["candles"]
                f.write(json.dumps(x) + "\n")
    gk = cached(gecko_path)
    with gecko_path.open("a") as f:
        for mint, g in day_grads.ts.items():
            c = have[mint]
            if (not c or c[0][0] > g) and mint not in gk and mint in pools.index:
                gk[mint] = (x := pump_fetch.gecko(mint, pools[mint], g - 3600, g + 7 * 3600))["candles"]
                f.write(json.dumps(x) + "\n")
    return {m: gk.get(m) or have[m] for m in day_grads.index}


def picks(day_grads: pd.DataFrame, candles: dict, lag: int) -> pd.DataFrame:
    names = [f"tp{tp or '-'}_sl{sl or '-'}_h{h:g}" for tp, sl, h in GRAD_RULES]
    k = names.index(RULE)
    out = []
    for mint, g in day_grads.ts.items():
        rows, res = grad_coin((mint, float(g), candles[mint], lag))
        if not len(rows):
            continue
        rows["r"], rows["mo"] = res[:, k], res[:, len(names) + k]
        hit = rows[(rows.min_since_grad >= MIN_AFTER) & (rows.mcap >= MCAP) & (rows.vol5 >= VOL5) & (rows.ret5 >= RET5)
                   & rows.r.notna()]
        if len(hit):
            out.append(hit.iloc[:1])
    return pd.concat(out) if out else pd.DataFrame(columns=["mint", "ts", "r", "mo", "mcap_in"])


def summary(y: pd.Series) -> dict:
    return {"mean": y.mean(), "median": y.median(), "exbest": y.drop(y.idxmax()).mean() if len(y) > 1 else np.nan}


def run_day(grads: pd.DataFrame, pools: pd.Series, work: Path, day: str) -> dict:
    start = pd.Timestamp(day, tz="UTC").timestamp()
    day_grads = grads[(grads.ts >= start) & (grads.ts < start + 86400)]
    candles = candles_for(day_grads, pools, work)
    row = {"day": day, "forward": day >= FIRST_FORWARD_DAY, "graduations": len(day_grads),
           "with_data": sum(bool(c) and c[0][0] <= day_grads.ts[m] for m, c in candles.items())}
    for lag in (1, 2):
        p = picks(day_grads, candles, lag)
        if lag == 1:
            row["picks"] = len(p)
        for s in STAKES if lag == 1 else STAKES[:1]:
            y = pd.Series(grad_net(p.r.to_numpy(float), p.mcap_in.to_numpy(float), p.mo.to_numpy(float), s), index=p.index)
            for key, v in summary(y).items():
                row[f"{key}{s}" + ("" if lag == 1 else "_lag2")] = round(float(v), 4) if v == v else np.nan
    return row


def main():
    veri, work, days = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "solana_import.py"), str(veri),
                    str(work / "sol.db")], check=True)
    table = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame()
    grads, pools = graduations(work)
    for day in days:
        row = run_day(grads, pools, work, day)
        table = pd.concat([table[table.day != day] if len(table) else table, pd.DataFrame([row])]).sort_values("day")
        OUT.parent.mkdir(exist_ok=True)
        table.to_csv(OUT, index=False)
        print(f"{day}: {row['graduations']} mezuniyet ({row['with_data']} verili), {row['picks']} işlem; $100'da ortalama "
              f"{row['mean100']:.3f}x, ortanca {row['median100']:.3f}x, en iyi hariç {row['exbest100']:.3f}x; "
              f"$300 {row['mean300']:.3f}x; 2 dk gecikmeyle {row['mean100_lag2']:.3f}x")
    fwd = table[table.forward.astype(bool)]
    if len(fwd):
        n = fwd.picks.sum()
        w = (fwd.mean100 * fwd.picks).sum() / n if n else np.nan
        print(f"İleri test toplamı ({len(fwd)} gün, {n} işlem): $100'da işlem başı {w:.3f}x; kârlı gün "
              f"{int((fwd.mean100 > 1).sum())}/{len(fwd)}")


if __name__ == "__main__":
    main()
