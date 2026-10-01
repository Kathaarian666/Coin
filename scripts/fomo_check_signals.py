"""Score the bot's own early signals (from /disari) on real Fomo prices (scripts/fomo_download.py data).

  python scripts/fomo_check_signals.py <trades.db> <signals.txt>

Each line: first 12 hex digits of the coin, unix time, E (⚡ alert) or A (rule A shadow), v2 momentum.
Same trade replay as scripts/fomo_replay.py (entry at the first buy `delay` s later, 2x/3x on two buys in a
row, else the median price around the hour).
"""

import statistics
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fomo_replay import DELAYS, FEE_MIN, FEE_PCT, POSITION, TARGETS, outcome  # noqa: E402
from rhscanner.strategy import trade_pnl  # noqa: E402


def main():
    db = sqlite3.connect(sys.argv[1])
    ids = {addr[2:14]: i for i, addr in db.execute("SELECT id, addr FROM names WHERE kind = 'token'")}
    first, last = db.execute("SELECT MIN(ts), MAX(ts) FROM trades").fetchone()
    groups: dict[str, list] = {}
    missing = 0
    rows = [ln.split() for ln in Path(sys.argv[2]).read_text().splitlines() if len(ln.split()) == 4]
    for prefix, ts, code, mom in rows:
        ts, mom = float(ts), int(mom)
        token = ids.get(prefix.lower())
        if token is None or not first <= ts <= last - 5400:
            missing += 1
            continue
        trades = db.execute("SELECT ts, side, usd, amount FROM trades WHERE token = ? ORDER BY ts, block",
                            (token,)).fetchall()
        tss = [t[0] for t in trades]
        side = [t[1] for t in trades]
        price = [(t[2] / t[3]) if t[2] and t[3] else None for t in trades]
        res = {d: outcome(tss, side, price, ts, d, TARGETS) for d in DELAYS}
        if res[DELAYS[0]] is None:
            missing += 1
            continue
        names = ["⚡ erken bildirim"] if code == "E" else (
            ["A gölge mom ≥90"] if mom >= 90 else ["A gölge mom 85-89"] if mom >= 85 else ["A gölge mom 80-84"])
        for name in names + ["hepsi"]:
            groups.setdefault(name, []).append(res)
    print(f"{len(rows)} satır, {missing} tanesi veride yok / ölçülemedi\n")
    for name, items in groups.items():
        print(f"{name} ({len(items)})")
        for d in DELAYS:
            for target in TARGETS:
                pnl = [trade_pnl([(1.0, r[d][target])], POSITION, FEE_PCT, FEE_MIN) for r in items if r[d]]
                if not pnl:
                    continue
                trim = statistics.mean(sorted(pnl)[: max(1, int(len(pnl) * 0.95))])
                hit = 100 * sum(1 for r in items if r[d] and r[d][target] == target) / len(pnl)
                print(f"   {d} sn, {target:g}x/60dk: ort {statistics.mean(pnl):+.1f}$ · medyan "
                      f"{statistics.median(pnl):+.1f}$ · %5 hariç {trim:+.1f}$ · hedef %{hit:.0f} · kârlı %"
                      f"{100 * sum(1 for p in pnl if p > 0) / len(pnl):.0f}")
        print()


if __name__ == "__main__":
    main()
