"""Fresh-day test (PROJE.md §0 A2): the paper model exactly as the bot runs it (rhscanner/paper_model.json), on
5th-buyer moments after its training data ended, i.e. coins it never saw.

  python scripts/fresh_test.py <trades.db> <winners_old.parquet> <winners_new.parquet> [<walk-forward picks.parquet>]
                               [--picks <out.parquet>]   the bot-like picks (coin, ts, score, is_pons, pct by rank in
                                                         1-top..1) for scripts/exit_truth.py / exit_truth_rules.py
                               [--holder]                the second model (paper_model_h.json; winners with holder
                                                         features, scripts/transfer_features.py)
                               [--top <share>=0.02]      the pick share (the bot: paper.TOP)
                               [--model <model.json>]    another exported model (e.g. last week's, for a fair test)

winners_new = scripts/winner_study.py over the recent days with the latest data (longer follow-up); its coins
replace theirs in winners_old, which supplies the first buyers' history (rise_study.add_history, outcome known
1 h later). Selection like the bot: score >= the 98th percentile of the scores of the 48 h before (and, side by
side, the exported starting bar). Outcomes follow PROJE.md §6: a moment without a 2x counts as "no" only after
24 h of data (2x within 1 h: after 1 h). Simulation like scripts/trade_sim.py: 30 s late, rule "iz", sizes
4/2/1 % by rank, $1000, brüt and masraflı; positions still open are valued at the last price.
The reference line is the walk-forward top 2 % of the research (scripts/profit_study.py output for k = 5).
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import rise_study  # noqa: E402
import trade_sim  # noqa: E402
from rhscanner import paper  # noqa: E402
from security_extra import depth_at  # noqa: E402

K = paper.CHECKPOINT_BUYERS
WINDOW = 48 * 3600
DELAY = trade_sim.WEEKLY_DELAY


def outcome_line(g: pd.DataFrame) -> str:
    ever = g.t2x_h.notna()
    known = ever | (g.obs_h >= 24)
    h1 = g.t2x_h.fillna(99) <= 1
    known1 = h1 | (g.obs_h >= 1)
    a = f"2x (süresiz) %{100 * ever[known].mean():.0f} ({int(ever[known].sum())}/{int(known.sum())})" if known.any() else "2x (süresiz) -"
    b = f"1 saatte 2x %{100 * h1[known1].mean():.0f} ({int(h1[known1].sum())}/{int(known1.sum())})" if known1.any() else ""
    pend = int((~known).sum())
    return f"{a} · {b}" + (f" · {pend} coin henüz 24 saat izlenmedi" if pend else "")


def build_alerts(db, picks: pd.DataFrame, rank_col: str = "score") -> list[dict]:
    """trade_sim alerts for the picks: 30 s late at the last buy price then, sizes 4/2/1 % by rank."""
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    alerts = []
    for r in picks.itertuples():
        g = pd.read_sql("SELECT ts, side, usd, amount FROM trades WHERE token = ? ORDER BY ts", db,
                        params=(names[r.coin],))
        ts, side, usd = g.ts.values, g.side.values, g.usd.values
        px = np.where(g.amount > 0, g.usd / g.amount.where(g.amount > 0), np.nan)
        b = (side == 1) & np.isfinite(px)
        p_alert = px[b & (ts <= r.ts)][-1]
        t_in = r.ts + DELAY
        p_in = px[b & (ts <= t_in)][-1]
        ev, kind = trade_sim.path_events(ts, px, side, t_in, p_in, p_alert, data_end)
        alerts.append(dict(t_in=t_in, p_in=p_in, depth=depth_at(px[b], usd[b], ts[b], r.ts), events=ev, kind=kind,
                           pct=getattr(r, rank_col)))
    med = np.nanmedian([a["depth"] for a in alerts])
    for a, q in zip(alerts, pd.Series([a["pct"] for a in alerts]).rank(pct=True)):
        a["size"] = 0.04 if q > 2 / 3 else 0.02 if q > 1 / 3 else 0.01
        if not np.isfinite(a["depth"]):
            a["depth"] = med
    return alerts


def bank_line(alerts: list[dict]) -> str:
    g = trade_sim.simulate(alerts, "iz", 1000, False) / 1000
    gc = trade_sim.simulate(alerts, "iz", 1000, True) / 1000
    stop = np.mean([a["kind"] == "stop" for a in alerts])
    return f"kasa $1000 → brüt {g:.3f}x, masraflı {gc:.3f}x · %50 zarar-kes %{100 * stop:.0f}"


def simulate(db, picks: pd.DataFrame) -> str:
    return bank_line(build_alerts(db, picks))


def main():
    argv = list(sys.argv)
    opts = {}
    for flag in ("--picks", "--top", "--model"):
        if flag in argv:
            i = argv.index(flag)
            opts[flag] = argv[i + 1]
            del argv[i:i + 2]
    out, top = opts.get("--picks"), float(opts["--top"]) if "--top" in opts else None
    holder = "--holder" in argv
    argv = [a for a in argv if a != "--holder"]
    top = top or paper.TOP
    db = sqlite3.connect(argv[1], timeout=300)
    old, new = pd.read_parquet(argv[2]), pd.read_parquet(argv[3])
    w = pd.concat([old[~old.coin.isin(set(new.coin))], new], ignore_index=True)
    w = rise_study.add_history(w[w.k == K].copy())
    path = Path(opts["--model"]) if "--model" in opts else paper.MODEL_H_PATH if holder else paper.MODEL_PATH
    model = paper.Model(json.loads(path.read_text()))
    w["score"] = [model.score({c: getattr(r, c) for c in model.features}) for r in w.itertuples()]
    w = w.sort_values("ts").reset_index(drop=True)
    ts, sc = w.ts.values, w.score.values
    bars = []
    for i, t in enumerate(ts):
        lo = np.searchsorted(ts, t - WINDOW)
        bars.append(np.percentile(sc[lo:i], 100 * (1 - top)) if i - lo >= 200 else np.nan)
    w["bar"] = bars
    fresh = w[w.ts > model.trained_until]
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    print(f"Model {pd.to_datetime(model.trained_until, unit='s'):%d %b %H:%M} UTC'ye kadarki anlarla eğitildi. Taze: "
          f"{pd.to_datetime(fresh.ts.min(), unit='s'):%d %b %H:%M} – {pd.to_datetime(fresh.ts.max(), unit='s'):%d %b %H:%M}, "
          f"{len(fresh)} coin 5. alıcıya ulaştı; veri sonu {pd.to_datetime(data_end, unit='s'):%d %b %H:%M}.\n")
    print(f"{'hepsi':>28}: {outcome_line(fresh)}")
    for label, sel in [(f"en iyi %{100 * top:g} (bot gibi, 48 sa)", fresh[fresh.score >= fresh.bar]),
                       (f"en iyi %2 (sabit eşik {model.bar:.3f})", fresh[fresh.score >= model.bar])]:
        print(f"{label:>28}: {len(sel)} seçim · {outcome_line(sel)}")
        if len(sel):
            print(f"{'':>28}  {simulate(db, sel.sort_values('ts'))}")
    for day, g in fresh.groupby(fresh.ts // 86400):
        sel = g[g.score >= g.bar]
        print(f"{pd.to_datetime(day * 86400, unit='s'):%d %b}: {len(g)} coin, {len(sel)} seçim · {outcome_line(sel)}")
    if out:
        sel = fresh[fresh.score >= fresh.bar].sort_values("ts").copy()
        sel["pct"] = 1 - top + top * sel.score.rank(pct=True)  # their rank among the picks (sizes, top 1 %)
        sel.to_parquet(out, index=False)
        print(f"\nseçimler yazıldı: {out}")
    if len(argv) > 4:  # the research's walk-forward top 2 % for comparison
        ref = pd.read_parquet(argv[4])
        last = ref[ref.ts >= ref.ts.max() - 7 * 86400]
        print(f"\nKarşılaştırma, araştırmanın walk-forward en iyi %2'si: tümü {len(ref)} seçim · {outcome_line(ref)}")
        print(f"{'son haftası':>28}: {len(last)} seçim · {outcome_line(last)}")


if __name__ == "__main__":
    main()
