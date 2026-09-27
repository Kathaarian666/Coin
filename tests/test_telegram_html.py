"""Every message the bot sends is parsed as Telegram HTML; a stray "<" makes Telegram refuse it and the
command then answers nothing. Only <b>, <i>, <code> and <a href> are used."""

import re

from rhscanner.outcomes import rug_filter_sweep, summarize
from rhscanner.report import (format_analysis, format_backtest, format_findings, format_scorecard, format_strategies,
                              format_sweep, format_winners)

ALLOWED = re.compile(r"</?(b|i|code)>|<a href=\"[^\"]*\">|</a>")


def assert_valid(messages):
    for text in messages if isinstance(messages, list) else [messages]:
        stripped = ALLOWED.sub("", text)
        assert "<" not in stripped and ">" not in stripped.replace("&gt;", ""), stripped[:300]


def sig(**f):
    return {"trust": 40, "momentum": 80, "ts": 1.0, "max_60": 2.0, "max_all": 6.0, "ret_60": 1.1, "rugged": False,
            "kind": "alert", "p0": 1.0, "features": {"momentum_v2": 80, "buyers_10m": 8, "buy_usd_10m": 300, **f}}


def test_every_report_is_valid_telegram_html():
    s = summarize([sig()])
    assert_valid(format_scorecard(24, [("Bildirim gidenler, rug riski 🟢 düşük (<20)", s), ("Momentum 🧊 <45", s)],
                                  [("🔴 ÇIK", {"n": 0})], {"alert": 2}))
    assert_valid(format_sweep(168, 10, 3, [{"min_momentum": 75, "min_score": 30, **s, "recall": 50.0}], (75, 30),
                              rug_filter_sweep([sig()], 75, 30)))
    halves = [(n, {"v1": s, "v2": s, "added": s, "dropped": {"n": 0}, "all": s}) for n in ("Eski yarı", "Tümü")]
    assert_valid(format_backtest(168, 30, 75, halves, True, s, 10))
    assert_valid(format_analysis(168, 40, [("rug riski puanı", [("0–20", s), ("<5", s)])]))
    assert_valid(format_findings(72, s, [("liq_usd_low", s)]))
    assert_valid(format_strategies(168, 100, [("2x'te sat (yoksa 1 saatte)", {"n": 1, "total": 5.0, "per_trade": 5.0,
                                                "win_rate": 100.0, "best": 5.0, "without_best": 0.0, "exits": 0})]))
    winner = {"symbol": "A<B", "multiple": 12.0, "hours_to_peak": 3, "peak_fdv": 50_000, "signals": [
        {**sig(), "kind": "shadow", "trust": None, "entry_vs_start": 1.3, "peak_after": 9.5, "before_peak": True}]}
    bars = {"min_score": 30, "min_momentum": 75, "min_buyers": 10, "min_buy_usd": 500, "max_rug": 60}
    assert_valid(format_winners(7, 10, [winner], 30, bars))
