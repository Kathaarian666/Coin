"""Every message the bot sends is parsed as Telegram HTML; a stray "<" makes Telegram refuse it and the
command then answers nothing. Only <b>, <i>, <code> and <a href> are used."""

import re

from rhscanner.report import format_paper, format_paper_alert, format_report

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


def test_paper_reports_are_valid_telegram_html():
    s = {"scored": 700, "alerts": 14, "closed": 9, "x2": 7, "stop": 3, "mean": 0.42, "median": -0.2, "win": 0.5,
         "bank": 1234.5, "latency": 6.0}
    empty = {"scored": 0, "alerts": 0, "closed": 0, "x2": 0, "stop": 0, "mean": None, "median": None, "win": None,
             "bank": 1000.0, "latency": None}
    rows = [("A<B>", {"ts": 1.79e9, "kind": "2x", "ret": 0.8, "closed": 0}),
            ("C&D", {"ts": 1.79e9, "kind": None, "ret": None, "closed": 0}),
            ("E", {"ts": 1.79e9, "kind": "stop", "ret": -0.55, "closed": 1})]
    assert_valid([format_paper(24, s, rows, 1.79e9), format_paper(None, empty, [], None),
                  format_paper_alert("<X>", "0x" + "1" * 40, 1.2e-9, 0.61, 0.04, 7.0)])
