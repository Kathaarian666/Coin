"""The blind-bot alarm (rhscanner/watchdog.py)."""
import sqlite3

from rhscanner import watchdog as wd
from test_telegram_html import assert_valid

H = 3600


def db_with(counts):
    """fomo_log with counts[i] trades in the hour ending i hours before t=10 days."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE fomo_log (block INTEGER, ts REAL, token TEXT, side INTEGER, trader TEXT, usd REAL, amount TEXT)")
    now = 10 * 86400
    rows = [(0, now - i * H - (j + 1) * H / (n + 1), "t", 1, "w", 1.0, "1") for i, n in enumerate(counts) for j in range(n)]
    db.executemany("INSERT INTO fomo_log VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return db, now


def test_silent_fires_once_and_recovers():
    w = wd.Watchdog(0.0)
    assert w.step(wd.SILENT_S - 1, None, "5") == []
    out = w.step(wd.SILENT_S, None, "5")
    assert len(out) == 1 and "kör" in out[0]
    assert w.step(wd.SILENT_S + 600, None, "5") == []  # no repeat
    w.seen(wd.SILENT_S + 700)
    out = w.step(wd.SILENT_S + 760, None, "6")
    assert len(out) == 1 and "yeniden" in out[0]
    assert_valid(out)


def test_thin_market_vs_blind_bot():
    normal, _ = db_with([100] * (8 * 24))
    db, now = db_with([2] * 6 + [100] * (8 * 24 - 6))  # last 6 h: 2 an hour (the 26 Oct case)
    recent, base = wd.thin_counts(db, now)
    assert recent == 12 and abs(base - 600) < 1
    assert "thin" in wd.problems(now, now, recent, base)
    assert "thin" not in wd.problems(now, now, *wd.thin_counts(normal, now))
    assert "thin" not in wd.problems(now, now, 0, 50.0)  # too little history to judge
    w = wd.Watchdog(now - 3600)
    w.seen(now)  # trades still come, only few
    out = w.step(now, db, "9")
    assert len(out) == 1 and "düştü" in out[0]
    assert_valid(out)
    assert_valid(wd.message("thin", False, now, now, 500, 600.0, "9"))
