from rhscanner.outcomes import rug_filter_sweep, rug_risk_of
from rhscanner.report import format_report, format_sweep
from rhscanner.rugrisk import rug_bucket, rug_risk

RISKY = {"buyers_10m": 12, "buy_usd_10m": 300, "hold_rate_30m": 0.6, "fomo_share_h1": 0.1, "age_min": 5}
CLEAN = {"buyers_10m": 12, "buy_usd_10m": 2400, "hold_rate_30m": 0.95, "fomo_share_h1": 1.0, "age_min": 90}


def test_rug_risk_adds_up_the_warning_signs():
    score, reasons = rug_risk(RISKY)
    assert score == 25 + 20 + 15 + 10 + 10 and reasons[0].startswith("alıcı başına küçük alım")
    assert rug_risk(CLEAN) == (0, [])
    assert rug_risk({}) == (0, [])  # nothing recorded: no points
    assert [rug_bucket(s) for s in (0, 20, 40, None)] == ["🟢 düşük (<20)", "🟠 orta (20-39)", "🔴 yüksek (40+)", "?"]
    assert rug_risk_of({"features": RISKY}) == 80 and rug_risk_of({"features": {**CLEAN, "rug_risk": 55}}) == 55


def test_rug_filter_sweep_and_alert_line():
    def sig(features, rugged, big):
        return {"trust": 60, "momentum": 80, "max_60": 1.0, "max_all": 6.0 if big else 1.0, "ret_60": 1.0,
                "rugged": rugged, "features": {**features, "momentum_v2": 80}}

    results = [sig(RISKY, True, False)] * 4 + [sig(CLEAN, False, True)] * 6
    rows = dict(rug_filter_sweep(results, 75, 30))
    assert rows["filtre yok"]["rugged"] == 40.0 and rows["rug riski <40"]["rugged"] == 0.0
    assert rows["rug riski <40"]["kept_winners"] == 6 and rows["rug riski <40"]["winners"] == 6
    text = "\n".join(format_sweep(168, 10, 6, [], (75, 30), list(rows.items())))
    assert "rug riski &lt;40: 6 bildirim" in text and "5x'lerden kalan 6/6" in text
    report = {"token": "0x" + "a" * 40, "score": 60, "findings": [], "rug_risk": {"score": 45, "reasons": ["x", "y"]}}
    assert "Rug riski: 🔴 yüksek" in format_report(report, "https://example.org")
