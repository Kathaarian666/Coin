import sqlite3

from rhscanner.exits import breakeven_multiple
from rhscanner.outcomes import OutcomeLog
from rhscanner.report import format_strategies
from rhscanner.strategy import simulate, take_profit, trade_pnl

MOON = [(0, 1.0), (5, 1.5), (30, 2.5), (60, 1.2), (1440, 8.0)]
RUG = [(0, 1.0), (30, 0.5), (60, 0.05)]


def test_fees_match_breakeven():
    be = breakeven_multiple(5.0)
    assert abs(trade_pnl([(1.0, be)], 5.0, 0.5, 0.95)) < 0.02
    assert trade_pnl([(1.0, 0.0)], 5.0, 0.5, 0.95) == -5.0


def test_rules_on_paths():
    assert take_profit(2.0, 60)(MOON, None) == [(1.0, 2.0)]
    assert take_profit(2.0, 1440, share=0.5)(MOON, None) == [(0.5, 2.0), (0.5, 8.0)]
    assert take_profit(2.0, 60)(RUG, None) == [(1.0, 0.05)]
    rows = dict(simulate([(MOON, None), (RUG, 30)], 5.0, 0.5, 0.95))
    assert rows["24 saat tut, sat"]["n"] == 2 and rows["24 saat tut, sat"]["best"] > 25
    assert rows["🔴 ÇIK gelince sat (yoksa 24 saatte)"]["win_rate"] == 50.0  # the rug is sold at 0.5x on ÇIK
    text = "\n".join(format_strategies(168, 5.0, list(rows.items())))
    assert text.count("toplam") == len(rows) and "1." in text


def test_alert_paths_from_the_log():
    log = OutcomeLog(sqlite3.connect(":memory:"))
    log.record("0xa", "alert", ts=1000)
    log.record("0xa", "exit", ts=2800)
    (sid,) = log.db.execute("SELECT id FROM signals WHERE kind = 'alert'").fetchone()
    log.db.executemany("INSERT INTO samples VALUES (?, ?, 0, ?, NULL)", [(sid, 0, 2.0), (sid, 60, 3.0)])
    assert log.alert_paths(hours=48, now=86400 + 1010) == [([(0, 1.0), (60, 1.5)], 30)]
