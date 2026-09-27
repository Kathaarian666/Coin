import sqlite3
import time

from rhscanner.fomo import FomoTrade
from rhscanner.journal import Journal, summarize_closed
from rhscanner.report import format_trades

TOKEN = "0x" + "A" * 40
ME = "0x" + "b" * 40


def trade(tx, side, usd, amount, ts):
    return FomoTrade(tx, 1, TOKEN, side, ME, usd, timestamp=ts, amount=amount)


def test_positions_from_trades():
    j = Journal(sqlite3.connect(":memory:"))
    now = time.time()
    assert j.record(trade("0x1", "buy", 5.0, 1000, now - 600))
    assert not j.record(trade("0x1", "buy", 5.0, 1000, now - 600))  # seen twice: once
    [p] = j.positions(24, now)
    assert not p["closed"] and p["held_share"] == 1.0 and p["pnl"] is None
    j.record(trade("0x2", "sell", 4.0, 500, now - 300))
    j.record(trade("0x3", "sell", 6.5, 500, now - 60))
    [p] = j.positions(24, now)
    assert p["closed"] and p["pnl"] == 5.5 and p["usd_out"] == 10.5
    p.update(symbol="HOODS", delay_min=3.0)
    s = summarize_closed([p])
    assert s["n"] == 1 and s["win_rate"] == 100.0 and s["avg_hold_min"] == 9 and s["avg_delay_min"] == 3.0
    text = format_trades(168, [p], s, wallet_set=True)
    assert "Kapanan 1 işlem: +$5.50" in text and "HOODS: $5.00 → $10.50 (+5.50$)" in text
    assert "/cuzdan" in format_trades(168, [], {"n": 0}, wallet_set=False)
