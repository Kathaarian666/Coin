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


def test_v2_rewards_small_young_fomo_coins_and_penalises_late_big_ones():
    from rhscanner.momentum import tuned_points

    fomo = {"buyers_10m": 12, "buyers_5m": 8, "buyers_prev_5m": 2, "buy_ratio_10m": 0.8, "hold_rate_30m": 0.9,
            "whale_share_10m": 0.3, "fomo_usd_60m": 5000}
    early = {"liquidity_usd": 2500, "fdv": 12_000, "volume_h1": 5000}
    late = {"liquidity_usd": 400_000, "fdv": 3_000_000, "volume_h1": 50_000}
    v1_early, _, _ = momentum_score(fomo, early, {"age_min": 30})
    v2_early, reasons, _ = momentum_score(fomo, early, {"age_min": 30}, v2=True)
    v1_late, _, _ = momentum_score(fomo, late, {"age_min": 2000})
    v2_late, _, _ = momentum_score(fomo, late, {"age_min": 2000}, v2=True)
    assert v2_early > v1_early and v2_late < v1_late
    assert any("FDV $12,000" in r for r in reasons)
    # v1 is exactly the old rules: +12 acceleration, +6 Fomo share, +8 fresh, -10 thin liquidity
    # (a 30% top buyer was not "spread" before: that needed 25%); v2: +4, +6 spread, +10, +15 small FDV
    f = {**fomo, "fomo_share_h1": 1.0, "age_min": 30, "liquidity_usd": 2500, "fdv": 12_000}
    assert sum(d for d, _ in tuned_points(f, False)) == 12 + 6 + 8 - 10
    assert sum(d for d, _ in tuned_points(f, True)) == 4 + 6 + 10 + 15


def test_age_is_the_younger_of_launch_and_pool():
    import time as _time
    fomo = {"buyers_10m": 10}
    market = {"pair_created_at": (_time.time() - 3 * 3600) * 1000}
    _, _, extra = momentum_score(fomo, market, {"age_min": 2900})
    assert 170 <= extra["age_min"] <= 190  # HOODS: launched two days before, its USDG pool three hours
    _, _, extra = momentum_score(fomo, {}, {"age_min": 2900})
    assert extra["age_min"] == 2900
