"""What to do once a pick hits 5x (PROJE.md §0 B6): sell everything at once (the bot's rule) or keep some of it a few
minutes / until the price turns? The 5x is seen on Fomo (two buys in a row at >= 5x the alert price, as the bot);
after it, the position is valued on-chain from scripts/exit_truth.py's events (the venue Fomo last traded on at the
5x: Pons curve or the coin's V4 pool), 0 once that venue's liquidity was pulled.

  python scripts/after5x.py <trades.db> <picks.parquet> <events .jsonl> [<last exploration day>=2026-09-30] [--fetch]

--fetch first downloads the missing on-chain events of the picks that hit 5x, from the alert to 70 min after the 5x
(exit_truth.venue_prices; exit_truth.py's 24 h cache works too). Picks without a 5x sell at 3 h whatever the rule,
so only the 5x picks are compared: their multiple per rule, and what the rule changes per trade over all picks.

picks: walk-forward top 5 % (scripts/profit_study.py, k = 5) with coin, ts, pct. Rules after the 5x (every sale
happens <delay> s after its signal, at the on-chain value then):
- hepsi: all at the 5x
- yarı+T: half at the 5x, the rest T min later
- T dk: all T min after the 5x
- iz X: all when the on-chain price falls X below its peak since the 5x (or 60 min after the 5x)
- yarı+iz X: half at the 5x, the rest on the trail
A venue change after the 5x (the curve coin graduated) leaves the later value unknown: priced at the
last known value (hi) and at 0 (lo). Multiples are brüt, bought 30 s after the alert;
exploration days and the later days (final exam) apart.
"""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BPS = 9.93
DELAY_IN = 30
HOLD = 3 * 3600
TRAIL_MAX = 60 * 60
RULES = [("hepsi", 1.0, None, None)] + [(f"yarı+{t}dk", 0.5, t * 60, None) for t in (2, 5, 10, 20)] \
    + [(f"{t} dk", 0.0, t * 60, None) for t in (1, 2, 5, 10, 15, 20, 30)] \
    + [(f"iz %{int(x * 100)}", 0.0, None, x) for x in (0.2, 0.3, 0.5)] \
    + [(f"yarı+iz %{int(x * 100)}", 0.5, None, x) for x in (0.3, 0.5)]
DELAYS = (0, 30, 60)


class Venue:
    """The on-chain price after the 5x, relative to the price at the 5x block."""

    def __init__(self, ev, hb):
        trades = [x for x in ev if x[4] == "trade"]
        at = [x for x in trades if x[0] <= hb]
        self.ok = bool(at) and at[-1][3] > 0
        if not self.ok:
            return
        self.v, self.p0, self.hb = at[-1][2], at[-1][3], hb
        later = [x for x in ev if x[0] > hb or (x[0] == hb and x[4] == "pull")]
        self.path = [(x[0], x[3] / self.p0) for x in later if x[4] == "trade" and x[2] == self.v]
        pulls = [x[0] for x in later if x[4] == "pull" and x[2] == self.v]
        self.pull = pulls[0] if pulls else np.inf
        # the coin left the venue (e.g. the curve coin graduated): trades go on elsewhere after the venue's last
        # trade; trades in another pool while the venue still trades are not a move
        last_v = self.path[-1][0] if self.path else hb
        moved = [x[0] for x in later if x[4] == "trade" and x[2] != self.v and x[0] > last_v]
        self.moved = moved[0] if moved else np.inf

    def value(self, b):
        """(lo, hi) relative value at block b."""
        if b >= self.pull:
            return 0.0, 0.0
        last = 1.0
        for blk, r in self.path:
            if blk > b:
                break
            last = r
        return (0.0, last) if b >= self.moved else (last, last)

    def trail_signal(self, x, b_max):
        peak = 1.0
        for blk, r in self.path:
            if blk > b_max or blk >= self.pull or blk >= self.moved:
                break
            peak = max(peak, r)
            if r <= (1 - x) * peak:
                return blk
        return min(b_max, self.pull, self.moved)


def hits(db, picks, names):
    """{coin: (alert block, 5x block, 5x price / buy price)} of the picks that hit 5x on Fomo within 3 h."""
    out = {}
    for r in picks.itertuples():
        tr = np.array(db.execute("SELECT ts, block, side, usd, amount FROM trades WHERE token=? ORDER BY ts",
                                 (names[r.coin],)).fetchall(), float)
        ts, blk, side = tr[:, 0], tr[:, 1], tr[:, 2]
        px = np.where(tr[:, 4] > 0, tr[:, 3] / np.where(tr[:, 4] > 0, tr[:, 4], 1), np.nan)
        buy = (side == 1) & np.isfinite(px) & (px > 0)
        pa = px[buy & (ts <= r.ts)][-1]
        p_in = px[buy & (ts <= r.ts + DELAY_IN)][-1]
        b = buy & (ts > r.ts + DELAY_IN) & (ts <= r.ts + HOLD)
        hit = np.flatnonzero((px[b][1:] >= 5 * pa) & (px[b][:-1] >= 5 * pa))
        if len(hit):
            out[r.coin] = (int(blk[ts <= r.ts][-1]), int(blk[b][hit[0] + 1]), 5 * pa / p_in, int(blk[0]))
    return out


def fetch(db, hit, ev, path):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time
    import exit_truth as et
    curves = dict(db.execute("SELECT lower(token), lower(curve) FROM launches"))
    todo = [(c, curves.get(c), ab, first, hb + int(TRAIL_MAX * 1.15 * BPS)) for c, (ab, hb, _, first) in hit.items()
            if c not in ev]
    print(f"zincir olayları: {len(hit) - len(todo)} hazır, {len(todo)} indirilecek", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(4) as pool, (gzip.open if path.suffix == ".gz" else open)(path, "at") as out:
        for n, done in enumerate(as_completed([pool.submit(et.one, j) for j in todo])):
            token, e, err = done.result()
            if e is not None:
                ev[token] = [tuple(x) for x in e]
                out.write(json.dumps([token, e]) + "\n")
                out.flush()
            if n % 10 == 0:
                print(f"  {n}/{len(todo)} · {time.time() - t0:.0f} sn", flush=True)


def main():
    args = [a for a in sys.argv[1:] if a != "--fetch"]
    db = sqlite3.connect(args[0])
    picks = pd.read_parquet(args[1]).sort_values("ts")
    picks["coin"] = picks.coin.str.lower()
    path = Path(args[2])
    opener = gzip.open if path.suffix == ".gz" else open
    ev = {t: [tuple(x) for x in e] for t, e in (json.loads(line) for line in opener(path, "rt"))} if path.exists() else {}
    cut = pd.Timestamp(args[3] if len(args) > 3 else "2026-09-30").value / 1e9 + 86400
    names = {a.lower(): i for i, a in db.execute("SELECT id, addr FROM names WHERE kind='token'")}
    data_end = db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]
    picks = picks[picks.ts + HOLD < data_end]
    hit = hits(db, picks, names)
    if "--fetch" in sys.argv:
        fetch(db, hit, ev, path)
    rows = []
    for r in picks[picks.coin.isin(hit)].itertuples():
        _, hb, p5, _ = hit[r.coin]
        row = {"coin": r.coin, "ts": r.ts, "explore": r.ts < cut, "known": r.coin in ev}
        ven = Venue(ev[r.coin], hb) if r.coin in ev else None
        row["venue"] = bool(ven and ven.ok)
        for name, first, t, x in RULES:
            for d in DELAYS:
                if not row["venue"]:  # no on-chain price at the 5x: every rule valued as "all at 5x"
                    lo = hi = p5
                else:
                    db_ = int(d * BPS)
                    v0 = ven.value(hb + db_)
                    if t is not None:
                        v1 = ven.value(hb + int(t * BPS) + db_)
                    elif x is not None:
                        v1 = ven.value(ven.trail_signal(x, hb + int(TRAIL_MAX * BPS)) + db_)
                    else:
                        v1 = v0
                    lo = p5 * (first * v0[0] + (1 - first) * v1[0])
                    hi = p5 * (first * v0[1] + (1 - first) * v1[1])
                row[(name, d, "lo")], row[(name, d, "hi")] = lo, hi
        rows.append(row)
    df = pd.DataFrame(rows)
    picks["explore"] = picks.ts < cut
    for part, ex in (("keşif", True), ("final sınavı", False)):
        g, n_all = df[df.explore == ex], int((picks.explore == ex).sum())
        if not n_all:
            continue
        span = picks[picks.explore == ex].ts
        print(f"\n== {part}: {n_all} seçim ({pd.Timestamp(span.min(), unit='s'):%d %b} – "
              f"{pd.Timestamp(span.max(), unit='s'):%d %b}), 3 saatte 5x {len(g)} "
              f"(zincir verisi yok {int((~g.known).sum())}, 5x anında fiyat yok {int((g.known & ~g.venue).sum())})")
        print("kural          | 5x seçimlerde işlem başı ort (lo–hi), medyan, en iyi hariç | bütün seçimlerde işlem başı fark "
              + " | ".join(f"gecikme {d} sn" for d in DELAYS))
        base = {d: g[("hepsi", d, "lo")] for d in DELAYS}
        p5s = g[("hepsi", 0, "lo")]
        for name, *_ in RULES:
            cells = []
            for d in DELAYS:
                lo, hi = g[(name, d, "lo")], g[(name, d, "hi")]
                diff = (lo - base[0]).sum() / n_all
                cells.append(f"{lo.mean():.2f}–{hi.mean():.2f} · {lo.median():.2f} · {lo.drop(lo.idxmax()).mean():.2f} · "
                             f"{diff:+.3f}" + (f" · sıfır {int((lo < 0.05 * p5s).sum())}" if d == 0 else ""))
            print(f"{name:14s} | " + " | ".join(cells))
        weeks = ((g.ts - g.ts.min()) // (7 * 86400)).astype(int)
        print("haftalara göre 5x seçimlerde ort (gecikme 0): " + " · ".join(
            f"{name} " + "/".join(f"{w[(name, 0, 'lo')].mean():.2f}" for _, w in g.groupby(weeks))
            for name in ("hepsi", "5 dk", "10 dk", "15 dk", "yarı+10dk")))


if __name__ == "__main__":
    main()
