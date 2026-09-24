from rhscanner.fomo import FomoTracker, FomoTrade
from rhscanner.momentum import fomo_features, momentum_label, momentum_score

TOKEN = "0x" + "1" * 40
NOW = 10_000.0


def trade(side, trader, usd, ago):
    return FomoTrade("0x", 1, TOKEN, side, trader, usd, NOW - ago)


def tracker_with(trades):
    tracker = FomoTracker()
    for t in trades:
        tracker.add(t)
    return tracker


def test_features_measure_acceleration_holding_and_whales():
    trades = [trade("buy", f"0x{i}", 20, 60) for i in range(8)]           # 8 buyers in the last 5 min
    trades += [trade("buy", f"0xp{i}", 20, 400) for i in range(2)]        # 2 buyers 5-10 min ago
    trades += [trade("sell", "0x0", 10, 30), trade("buy", "0xwhale", 500, 90)]
    f = fomo_features(tracker_with(trades), TOKEN, now=NOW)
    assert (f["buyers_5m"], f["buyers_prev_5m"], f["buyers_10m"]) == (9, 2, 11)
    assert f["hold_rate_30m"] == round(1 - 1 / 11, 3)
    assert f["whale_share_10m"] == round(500 / 700, 3)


def test_accelerating_organic_fresh_token_scores_high():
    fomo = {"buyers_5m": 14, "buyers_prev_5m": 5, "buyers_10m": 22, "buy_ratio_10m": 0.8,
            "hold_rate_30m": 0.9, "whale_share_10m": 0.15, "fomo_usd_60m": 6000}
    market = {"volume_h1_all": 12_000, "liquidity_usd": 40_000, "change_h1": 80, "change_m5": 10,
              "socials": ["telegram", "twitter"], "websites": 1}
    score, reasons, extra = momentum_score(fomo, market, {"age_min": 25})
    assert score >= 90 and momentum_label(score)[1] == "Güçlü"
    assert extra == {"fomo_share_h1": 0.5, "age_min": 25}
    assert any("hızlanıyor" in r for r in reasons)


def test_fading_whale_driven_late_token_scores_low():
    fomo = {"buyers_5m": 1, "buyers_prev_5m": 8, "buyers_10m": 9, "buy_ratio_10m": 0.3,
            "hold_rate_30m": 0.4, "whale_share_10m": 0.7, "fomo_usd_60m": 100}
    market = {"volume_h1_all": 90_000, "liquidity_usd": 2_000, "change_h1": 900, "change_m5": -30}
    score, reasons, _ = momentum_score(fomo, market, {"age_min": 3000})
    assert score == 0 and momentum_label(score)[1] == "Zayıf"
    assert reasons[0].startswith("satış ağırlıklı") or reasons[0].startswith("yavaşlıyor")
