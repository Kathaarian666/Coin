"""Turns findings into a 0-100 safety score (higher = safer)."""

from .checks import Finding


def score(findings: list[Finding]) -> int:
    if any(f.severity == "critical" for f in findings):
        return 0
    return max(0, min(100, 100 - sum(f.penalty for f in findings)))


def level(value: int) -> tuple[str, str]:
    if value >= 75:
        return "🟢", "Düşük risk"
    if value >= 50:
        return "🟡", "Orta risk"
    if value > 0:
        return "🔴", "Yüksek risk"
    return "⛔", "TEHLİKELİ"
