"""Short-term momentum score (0-100) for hit-and-run trades.

Separate from the trust score: trust asks "can this rug or trap me?", momentum
asks "is real buying accelerating right now?". Weights are a first guess from
the research (fast liquidity build-up and organic, non-bot flow are the strongest
launchpad predictors; social presence multiplies graduation odds) and are meant
to be recalibrated from the outcome log (see outcomes.py and /karne).
"""

import time

from .fomo import FomoTracker


def fomo_features(tracker: FomoTracker, token: str, now: float | None = None) -> dict:
    """Order-flow features from the Fomo trades seen for a token."""
    now = now or time.time()
    trades = list(tracker.trades.get(token.lower(), ()))

    def window(start: float, end: float) -> list:
        """Trades between `start` and `end` seconds ago."""
        return [t for t in trades if now - start < t.timestamp <= now - end]

    last5, prev5 = window(300, 0), window(600, 300)
    last10, last30 = window(600, 0), window(1800, 0)
    buyers = lambda ts: {t.trader for t in ts if t.side == "buy"}  # noqa: E731
    usd = lambda ts, side: sum(t.usd or 0 for t in ts if t.side == side)  # noqa: E731

    per_buyer: dict[str, float] = {}
    for t in last10:
        if t.side == "buy":
            per_buyer[t.trader] = per_buyer.get(t.trader, 0) + (t.usd or 0)
    buy10, sell10 = usd(last10, "buy"), usd(last10, "sell")
    buyers30 = buyers(last30)
    sellers30 = {t.trader for t in last30 if t.side == "sell"}
    return {
        "buyers_5m": len(buyers(last5)),
        "buyers_prev_5m": len(buyers(prev5)),
        "buyers_10m": len(buyers(last10)),
        "buy_usd_10m": round(buy10, 2),
        "sell_usd_10m": round(sell10, 2),
        "buy_ratio_10m": round(buy10 / (buy10 + sell10), 3) if buy10 + sell10 else None,
        "hold_rate_30m": round(1 - len(buyers30 & sellers30) / len(buyers30), 3) if buyers30 else None,
        "whale_share_10m": round(max(per_buyer.values()) / buy10, 3) if per_buyer and buy10 else None,
        "fomo_usd_60m": round(usd(window(3600, 0), "buy") + usd(window(3600, 0), "sell"), 2),
    }


def momentum_score(fomo: dict, market: dict, launch: dict | None = None) -> tuple[int, list[str], dict]:
    """Returns (score, reasons, extra features). market: analyzer.market_summary output."""
    launch = launch or {}
    points = 50.0
    reasons: list[tuple[float, str]] = []

    def add(delta: float, why: str):
        nonlocal points
        points += delta
        reasons.append((delta, why))

    b10 = fomo.get("buyers_10m", 0)
    if b10 >= 30:
        add(15, f"çok hızlı alım: 10 dk'da {b10} alıcı")
    elif b10 >= 20:
        add(10, f"hızlı alım: 10 dk'da {b10} alıcı")
    elif b10 >= 10:
        add(5, f"10 dk'da {b10} alıcı")

    b5, prev = fomo.get("buyers_5m", 0), fomo.get("buyers_prev_5m", 0)
    accel = b5 / max(prev, 1)
    if b5 >= 4 and accel >= 2:
        add(12, f"hızlanıyor: son 5 dk {b5} alıcı (önceki 5 dk {prev})")
    elif b5 >= 3 and accel >= 1.2:
        add(6, "alım hızı artıyor")
    elif prev >= 4 and accel <= 0.5:
        add(-12, f"yavaşlıyor: son 5 dk {b5} alıcı (önceki {prev})")

    ratio = fomo.get("buy_ratio_10m")
    if ratio is not None:
        if ratio >= 0.7:
            add(8, f"alım ağırlıklı akış (%{ratio * 100:.0f} alım)")
        elif ratio <= 0.4:
            add(-12, f"satış ağırlıklı akış (%{ratio * 100:.0f} alım)")

    hold = fomo.get("hold_rate_30m")
    if hold is not None:
        if hold >= 0.8:
            add(8, f"alıcıların %{hold * 100:.0f}'i hâlâ tutuyor")
        elif hold <= 0.5:
            add(-10, f"alıcıların yarısından fazlası sattı bile (%{hold * 100:.0f} tutuyor)")

    whale = fomo.get("whale_share_10m")
    if whale is not None:
        if whale >= 0.5:
            add(-10, f"alımın %{whale * 100:.0f}'i tek cüzdandan")
        elif whale <= 0.25:
            add(4, "alım çok sayıda cüzdana yayılmış")

    smart = fomo.get("smart_buyers_10m", 0)
    if smart >= 2:
        add(10, f"son 10 dk'da {smart} akıllı Fomo cüzdanı aldı")
    elif smart == 1:
        add(5, "son 10 dk'da 1 akıllı Fomo cüzdanı aldı")

    features: dict = {}
    volume_h1 = market.get("volume_h1_all") or market.get("volume_h1")
    if volume_h1:
        share = min(1.0, fomo.get("fomo_usd_60m", 0) / volume_h1)
        features["fomo_share_h1"] = round(share, 3)
        if share >= 0.3:
            add(6, f"organik akış: 1s hacmin %{share * 100:.0f}'i Fomo kullanıcılarından")
        elif share < 0.05 and volume_h1 > 20_000:
            add(-6, "hacmin neredeyse tamamı Fomo dışından (bot/sniper olabilir)")

    age = launch.get("age_min")
    if age is None and market.get("pair_created_at"):
        age = (time.time() - market["pair_created_at"] / 1000) / 60
    if age is not None:
        features["age_min"] = round(age, 1)
        if age <= 60:
            add(8, f"taze: {age:.0f} dk önce çıktı")
        elif age <= 360:
            add(3, f"{age / 60:.1f} saatlik")
        elif age > 1440:
            add(-5, f"{age / 1440:.0f} günlük (vur-kaç için geç olabilir)")

    change_h1, change_m5 = market.get("change_h1"), market.get("change_m5")
    if change_h1 is not None and change_h1 > 500:
        add(-8, f"son 1 saatte zaten +%{change_h1:.0f} (geç kalınmış olabilir)")
    if change_m5 is not None and change_m5 <= -20:
        add(-8, f"son 5 dakikada %{change_m5:.0f} düşüş")

    socials = set(market.get("socials") or [])
    if "telegram" in socials:
        add(5, "Telegram var")
    if "twitter" in socials:
        add(3, "X hesabı var")
    if market.get("websites"):
        add(2, "web sitesi var")

    liquidity = market.get("liquidity_usd")
    if liquidity is not None and liquidity < 3000:
        add(-10, f"likidite çok ince (${liquidity:,.0f}), kayma yüksek")

    score = int(max(0, min(100, round(points))))
    ordered = [why for delta, why in sorted(reasons, key=lambda r: -abs(r[0]))]
    return score, ordered, features


def momentum_label(score: int) -> tuple[str, str]:
    if score >= 70:
        return "🚀", "Güçlü"
    if score >= 45:
        return "🟡", "Orta"
    return "🧊", "Zayıf"
