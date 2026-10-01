"""Every message the bot sends is parsed as Telegram HTML; a stray "<" makes Telegram refuse it and the
command then answers nothing. Only <b>, <i>, <code> and <a href> are used."""

import re

from rhscanner.report import format_report

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
