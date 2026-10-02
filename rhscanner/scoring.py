"""Turns findings into a 0-100 safety score (higher = safer)."""

from .checks import Finding


# Checks whose absence means we cannot vouch for the token, with what to call them.
KEY_CHECKS_MISSING = {
    "holders_unknown": "cüzdan dağılımı",
    "v4_hooks_unknown": "V4 hook'u",
    "not_simulated": "honeypot simülasyonu",
    "sim_error": "honeypot simülasyonu",
    "no_pool": "havuz/likidite",
}
# Without them a token can look clean only for lack of evidence, so cap the score.
MISSING_DATA_CAP = 70


def missing_checks(findings: list[Finding]) -> list[str]:
    names = []
    for f in findings:
        # A downgraded (info) finding means other evidence covered it, e.g. real Fomo sells.
        name = KEY_CHECKS_MISSING.get(f.code)
        if name and f.severity != "info" and name not in names:
            names.append(name)
    return names


def score(findings: list[Finding]) -> int:
    if any(f.severity == "critical" for f in findings):
        return 0
    value = max(0, min(100, 100 - sum(f.penalty for f in findings)))
    if missing_checks(findings):
        value = min(value, MISSING_DATA_CAP)
    return value


def level(value: int) -> tuple[str, str]:
    if value >= 75:
        return "🟢", "Düşük risk"
    if value >= 50:
        return "🟡", "Orta risk"
    if value > 0:
        return "🔴", "Yüksek risk"
    return "⛔", "TEHLİKELİ"
