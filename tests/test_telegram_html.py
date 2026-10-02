"""Every message the bot sends is parsed as Telegram HTML; a stray "<" makes Telegram refuse it and the
command then answers nothing. Only <b>, <i>, <code> and <a href> are used."""

import re

from rhscanner.report import format_report, format_scan_log

ALLOWED = re.compile(r"</?(b|i|code)>|<a href=\"[^\"]*\">|</a>")


def assert_valid(messages):
    for text in messages if isinstance(messages, list) else [messages]:
        stripped = ALLOWED.sub("", text)
        assert "<" not in stripped and ">" not in stripped.replace("&gt;", ""), stripped[:300]


def test_alert_report_is_valid_telegram_html():
    report = {"token": "0x" + "1" * 40, "name": "A<B", "symbol": "<X>", "score": 40, "missing": ["holder <dağılımı>"],
              "findings": [{"code": "x", "severity": "high", "message": "vergi <%50"}],
              "fomo": {"window_min": 10, "buyers": 12, "sellers": 1, "buy_usd": 900, "sell_usd": 20},
              "market": {"fdv": 15000, "liquidity_usd": 5000}, "launch": {"age_min": 30, "dev_pct": 2.0}}
    assert_valid(format_report(report, "https://x", "🔥 <yükselen>"))


def test_record_report_is_valid_telegram_html():
    g = {"n": 3, "pending": 1, "mean": 12.5, "median": -3.0, "win": 0.33, "total": 37.5, "best": 90.0}
    empty = {"n": 0, "pending": 2, "mean": None, "median": None, "win": None, "total": 0, "best": None}
    s = {"scored": 10, "measured": 6, "pending": 3, "unmeasured": 1, "top10": g, "top20": empty, "all": g}
    assert_valid(format_scan_log(24, s, [("A<B>", 0.12, 50.0, 3.2), ("C&D", 0.1, None, None)], 1.79e9))
