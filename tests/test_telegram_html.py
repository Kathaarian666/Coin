"""Every message the bot sends is parsed as Telegram HTML; a stray "<" makes Telegram refuse it and the
command then answers nothing. Only <b>, <i>, <code> and <a href> are used."""

import re

from rhscanner.outcomes import lateness_table, rug_filter_sweep, summarize
from rhscanner.report import (format_analysis, format_backtest, format_early_grid, format_findings, format_lateness, format_scorecard, format_targets, format_strategies,
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
    assert_valid(format_backtest(168, 30, 75, halves, True, s, 10, {("A", 0): s, ("A", 80): s, ("B", 0): {"n": 0}}))
    assert_valid(format_analysis(168, 40, [("rug riski puanı", [("0–20", s), ("<5", s)])]))
    assert_valid(format_findings(72, s, [("liq_usd_low", s)]))
    combo = {"b5": 5, "prev": 1, "avg": 100, "hold": 0.9, "mom": 90, "n": 20, "n_old": 10, "n_new": 10,
             "old": 50.0, "new": -3.5, "late": None, "win": 60.0}
    assert_valid(format_early_grid(336, {"n": 30, "combos": [combo], "live": combo, "by_old": [combo],
                                         "steady": [combo]}))
    assert_valid(format_early_grid(336, {"n": 0, "combos": [], "live": None}))
    from rhscanner.strategy import target_table
    assert_valid(format_targets(168, 100, target_table([("⚡ Erken <test>", [[(0, 1.0), (5, 2.0), (10, 2.1)]]),
                                                        ("boş", [])], 100, 0.5, 0.95)))
    assert_valid(format_lateness(168, lateness_table([sig(runup_first=2.0, since_first_min=12, change_h1=600,
                                                          change_m5=-5, first_seen="shadow"), {**sig(first_seen="shadow", runup_first=1.2),
                                                          "path": [(0, 1.0), (5, 1.6)], "held_all": 1.0}])))
    assert_valid(format_strategies(168, 100, [("2x'te sat (yoksa 1 saatte)", {"n": 1, "total": 5.0, "per_trade": 5.0,
                                                "win_rate": 100.0, "best": 5.0, "without_best": 0.0, "exits": 0})]))
    winner = {"token": "0x" + "a" * 40, "symbol": "A<B", "multiple": 12.0, "hours_to_peak": 3, "peak_fdv": 50_000, "signals": [
        {**sig(), "kind": "shadow", "trust": None, "entry_vs_start": 1.3, "peak_after": 9.5, "before_peak": True}]}
    bars = {"min_score": 30, "min_momentum": 75, "min_buyers": 10, "min_buy_usd": 500, "max_rug": 60}
    assert_valid(format_winners(7, 10, [winner], 30, bars))


def test_signal_report():
    from rhscanner.report import format_signal
    s = {**sig(fdv=12000, age_min=30, findings=["liq_usd_low"]), "kind": "alert"}
    text = format_signal("HOODS", [s], {"alert": {"max_60": 3.0, "max_all": 45.0, "held_all": 40.0, "ret_60": 2.0,
                                                  "rugged": False}})
    assert_valid(text)
    assert "10 dk alıcı 8" in text and "FDV $12,000" in text and "kalıcı 40x" in text and "liq_usd_low" in text
    assert "kayıtlı sinyal yok" in format_signal("X", [], {})
