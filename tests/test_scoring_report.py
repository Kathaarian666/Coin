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
    text = format_report(report, "https://explorer", header="🔥 Test")
    assert "&lt;script&gt;" in text and "A&amp;B" in text and "<script>" not in text
    assert "Güven skoru: 70/100" in text and "alım %1.0 / satış %2.0" in text


def test_missing_key_checks_cap_the_score_and_are_listed():
    findings = [Finding("low", "holders_unknown", "x"), Finding("low", "v4_hooks_unknown", "y")]
    assert score(findings) == 70
    report = {"token": "0x" + "1" * 40, "name": "A", "symbol": "A", "score": 70, "findings": [],
              "missing": ["cüzdan dağılımı", "V4 hook'u"]}
    assert "Kontrol edilemeyenler: cüzdan dağılımı, V4 hook'u" in format_report(report, "https://x")
    # Fomo sells stand in for the simulation, which is then downgraded to info.
    assert score([Finding("info", "not_simulated", "z")]) == 100


def _alert_report():
    return {"token": "0x" + "1" * 40, "name": "Dark", "symbol": "DARK", "score": 70, "findings": [],
            "pool": {"pool": "0xpool"}, "market": {"price_usd": "1.0", "liquidity_usd": 200_000}}


def test_followup_confirms_sells_and_price():
    from rhscanner.report import format_followup
    recent = {"buyers": 6, "sellers": 3, "buy_usd": 900, "sell_usd": 300}
    text = format_followup(_alert_report(), recent, sellers_hour=4, market={"price_usd": "1.25", "liquidity_usd": 210_000},
                           minutes=15)
    assert "Takip · Dark" in text and "+25.0%" in text and "4 farklı Fomo kullanıcısı sattı" in text
    assert "rugpull" not in text


def test_followup_warns_on_no_sells_and_calls_a_clean_dip_healthy():
    from rhscanner.report import format_followup
    recent = {"buyers": 0, "sellers": 0, "buy_usd": 0, "sell_usd": 0}
    text = format_followup(_alert_report(), recent, sellers_hour=0, market={"price_usd": "0.5", "liquidity_usd": 150_000},
                           minutes=15)
    assert "Hâlâ hiç Fomo satışı yok" in text and "-50.0%" in text
    assert "sağlıklı geri çekilme olabilir" in text and "rugpull" not in text
    # with exit reasons the dip is not called healthy
    text = format_followup(_alert_report(), recent, 0, {"price_usd": "0.5"}, 15, [("warning", "Piyasada satış dalgası")])
    assert "Piyasada satış dalgası" in text and "sağlıklı" not in text


def test_exit_message():
    from rhscanner.report import format_exit
    text = format_exit(_alert_report(), [("strong", "Geliştirici satıyor: arzın %20.0'i → %2.0")], "strong",
                       {"price_usd": "0.8"}, 5)
    assert "ÇIK sinyali" in text and "Geliştirici satıyor" in text and "-20.0%" in text


def test_fee_line_in_alert():
    report = {"token": "0x" + "1" * 40, "name": "A", "symbol": "A", "score": 80, "findings": [],
              "fees": {"position": 5.0, "breakeven": 1.47}}
    assert "$5 pozisyonda komisyonla başa baş: <b>1.47x</b>" in format_report(report, "https://x")
