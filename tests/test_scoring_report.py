from rhscanner.checks import Finding
from rhscanner.report import format_report
from rhscanner.scoring import level, score


def test_score_penalties_and_critical_cap():
    assert score([Finding("good", "a", "x")]) == 100
    assert score([Finding("high", "a", "x"), Finding("medium", "b", "y")]) == 65
    assert score([Finding("critical", "a", "x"), Finding("good", "b", "y")]) == 0
    assert score([Finding("high", str(i), "x") for i in range(10)]) == 0


def test_levels():
    assert level(80)[1] == "Düşük risk"
    assert level(60)[1] == "Orta risk"
    assert level(10)[1] == "Yüksek risk"
    assert level(0)[1] == "TEHLİKELİ"


def test_report_escapes_token_name():
    report = {
        "token": "0x" + "1" * 40, "name": "<script>", "symbol": "A&B", "score": 70,
        "pool": {"dex": "v2"}, "honeypot": {"simulated": True, "buy_tax": 1.0, "sell_tax": 2.0},
        "findings": [Finding("high", "x", "Kara liste <var>").to_dict()],
    }
    text = format_report(report, "https://explorer", new=True)
    assert "&lt;script&gt;" in text and "A&amp;B" in text and "<script>" not in text
    assert "Güven skoru: 70/100" in text and "alım %1.0 / satış %2.0" in text
