"""Rug risk (0-100, higher = more likely to collapse), separate from trust and momentum.

/tarama showed that neither the trust score nor momentum moves the rug rate
(about 10% at every bar). The first /analiz did find features that do, and
this score adds them up; the points follow how far each one lifted the rug
rate over the ~10% base. Measured first (/analiz, /karne), not used to filter.
"""


def rug_points(f: dict) -> list[tuple[int, str]]:
    """f: recorded signal features (buyers_10m, buy_usd_10m, hold_rate_30m, fomo_share_h1, age_min...)."""
    out = []
    buyers, usd = f.get("buyers_10m"), f.get("buy_usd_10m")
    if buyers and usd is not None and usd / buyers < 74:
        out.append((25, f"alıcı başına küçük alım (${usd / buyers:.0f})"))  # rug 24% vs 6-8%
    hold = f.get("hold_rate_30m")
    if hold is not None and hold < 0.8:
        out.append((20, f"alıcıların %{(1 - hold) * 100:.0f}'i sattı bile"))  # rug 21% vs 7.5-12.6%
    share = f.get("fomo_share_h1")
    if share is not None and share < 0.23:
        out.append((15, f"hacmin %{(1 - share) * 100:.0f}'i Fomo dışından"))  # rug 18.9% vs 1.7-6.7%
    if usd is not None and usd < 550:
        out.append((10, f"10 dk'da az alım (${usd:,.0f})"))  # rug 20.5% vs 5.9-11.4%
    age = f.get("age_min")
    if age is not None and age < 14:
        out.append((10, f"çok yeni ({age:.0f} dk)"))  # rug 19.5% vs 1.5-12.4%
    return out


def rug_risk(f: dict) -> tuple[int, list[str]]:
    points = rug_points(f)
    return min(100, sum(p for p, _ in points)), [why for _, why in sorted(points, key=lambda p: -p[0])]


def rug_bucket(score: int | None) -> str:
    if score is None:
        return "?"
    return "🟢 düşük (<20)" if score < 20 else "🟠 orta (20-39)" if score < 40 else "🔴 yüksek (40+)"
