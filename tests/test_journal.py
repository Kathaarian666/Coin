import sqlite3

from rhscanner.exits import breakeven_multiple
from rhscanner.journal import Journal
from rhscanner.report import format_bought, format_sold, format_trades

TOKEN = "0x" + "a" * 40


def test_buy_sell_with_fees_and_alert_delay():
    j = Journal(sqlite3.connect(":memory:"))
    bought = j.buy(TOKEN, 5.0, 1.0, "HOODS", {"ts": 1000.0, "p0": 0.8}, now=1600.0)
    assert bought["fee"] == 0.95 and round(bought["vs_alert"], 2) == 1.25 and bought["delay_min"] == 10
    half = j.sell(TOKEN, 0.5, 4.0, now=2000.0)
    assert not half["closed"] and round(half["left_share"], 2) == 0.5 and half["net"] == round(4.05 / 2 * 4 - 0.95, 2)
    rest = j.sell(TOKEN, 1.0, 2.0, now=2500.0)
    assert rest["closed"] and rest["pnl"] == round(7.15 + 3.1 - 5.0, 2)
    assert j.sell(TOKEN, 1.0, 2.0) is None  # nothing open
    summary = j.closed_summary(24, now=3000.0)
    assert summary["n"] == 1 and summary["win_rate"] == 100.0 and summary["avg_delay_min"] == 10
    assert "10 dk sonra" in format_bought("HOODS", bought) and "Pozisyon kapandı" in format_sold("HOODS", 100, rest)
    assert "kapanan 1 işlem" in format_trades(24, [], summary)


def test_breakeven_price_sells_flat_and_buys_add_up():
    j = Journal(sqlite3.connect(":memory:"))
    j.buy(TOKEN, 5.0, 1.0)
    j.buy(TOKEN, 5.0, 3.0)
    [p] = j.open_positions()
    assert p["usd"] == 10.0 and round(p["entry_price"], 3) == 1.5  # 4.05 + 1.35 tokens
    fresh = Journal(sqlite3.connect(":memory:"))
    fresh.buy(TOKEN, 5.0, 1.0)
    assert abs(fresh.sell(TOKEN, 1.0, breakeven_multiple(5.0))["pnl"]) < 0.02
    text = format_trades(168, [(p, 12.0)], {"n": 0})
    assert "Açık pozisyonlar" in text and "$10 girdin → $12.00 (+2.00$)" in text
