"""Every message the bot sends is parsed as Telegram HTML; a stray "<" makes Telegram refuse it and the
command then answers nothing. Only <b>, <i>, <code> and <a href> are used."""

import re

from rhscanner.report import (format_5x, format_liquidity_warning, format_live_alert, format_paper,
                              format_paper_5x, format_paper_alert, format_report, format_safety,
                              format_time_up)

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
         "bank": 1234.5, "latency": 6.0, "x5": 3, "time5": 5, "pulled5": 1, "bank5": 1500.0}
    empty = {"scored": 0, "alerts": 0, "closed": 0, "x2": 0, "stop": 0, "mean": None, "median": None, "win": None,
             "bank": 1000.0, "latency": None, "x5": 0, "time5": 0, "pulled5": 0, "bank5": 1000.0}
    rows = [("A<B>", {"ts": 1.79e9, "kind": "2x", "ret": 0.8, "closed": 0}),
            ("C&D", {"ts": 1.79e9, "kind": None, "ret": None, "closed": 0}),
            ("E", {"ts": 1.79e9, "kind": "stop", "ret": -0.55, "closed": 1, "kind5": "5x", "ret5": 3.9}),
            ("F", {"ts": 1.79e9, "kind": "yok", "ret": -1.0, "closed": 1, "kind5": "süre", "ret5": -1.0,
                   "chain5": "çekildi"})]
    assert_valid([format_paper(24, s, rows, 1.79e9), format_paper(None, empty, [], None),
                  format_paper(24, s, rows, 1.79e9, s), format_paper(None, empty, [], None, empty),
                  format_paper_alert("<X>", "0x" + "1" * 40, 45_000.0, 0.61, 0.04, 7.0),
                  format_paper_alert("<X>", "0x" + "1" * 40, float("nan"), 0.61, None, 7.0),
                  format_paper_5x("<X>", "0x" + "1" * 40, 9.6)])


def test_live_messages_are_valid_telegram_html():
    token = "0x" + "1" * 40
    assert_valid([format_live_alert("<X>", token, 1_250_000.0, 0.61, [("toplam alım", "$1,200"), ("a<b", "%5 <")],
                                    ("ok", "satış simülasyonu geçti (vergi %0)"), 6.0),
                  format_live_alert("Y&Z", token, None, None, [], ("bilinmiyor", "V4 havuzu <yok>"), 9.0),
                  format_safety("<X>", token, 87, [("Fomo'da satış", "ok", "2 <satıcı>"), ("Likidite", "warn", "a&b"),
                                                     ("LP kilidi", "unknown", "bilinmiyor")], [("GoPlus", True), ("Gecko", False)]),
                  format_safety("Y", token, None, [], []),
                  format_5x("<X>", token, 14.0), format_time_up("<X>", token, 3),
                  format_liquidity_warning("<X>", token, 85.0)])
