"""Supply distribution: whale concentration, creator share, burned supply."""

from ..sources import Blockscout
from . import DEAD_ADDRESSES, Finding


def analyse_holders(
    holders: list[dict], total_supply: int, exclude: set[str], creator: str | None
) -> tuple[dict, list[Finding]]:
    """holders: Blockscout items ({"address": {"hash", "is_contract"}, "value"})."""
    findings: list[Finding] = []
    if not total_supply:
        return {}, [Finding("medium", "no_supply", "Toplam arz okunamadı")]

    exclude = {a.lower() for a in exclude}
    burned = 0
    wallets: list[tuple[str, int]] = []
    for item in holders:
        addr = (item.get("address") or {}).get("hash", "").lower()
        value = int(item.get("value") or 0)
        if addr in DEAD_ADDRESSES:
            burned += value
        elif addr not in exclude:
            wallets.append((addr, value))
    wallets.sort(key=lambda w: w[1], reverse=True)

    pct = lambda v: 100.0 * v / total_supply  # noqa: E731
    top10 = pct(sum(v for _, v in wallets[:10]))
    largest = pct(wallets[0][1]) if wallets else 0.0
    creator_pct = pct(sum(v for a, v in wallets if creator and a == creator.lower()))
    data = {
        "holder_count_sampled": len(holders),
        "top10_pct": round(top10, 2),
        "largest_pct": round(largest, 2),
        "creator_pct": round(creator_pct, 2),
        "burned_pct": round(pct(burned), 2),
    }

    if top10 > 50:
        findings.append(Finding("high", "top10_high", f"İlk 10 cüzdan arzın %{top10:.1f}'ini tutuyor"))
    elif top10 > 30:
        findings.append(Finding("medium", "top10_mid", f"İlk 10 cüzdan arzın %{top10:.1f}'ini tutuyor"))
    else:
        findings.append(Finding("good", "top10_ok", f"İlk 10 cüzdan: %{top10:.1f} (dağılım iyi)"))

    if largest > 15:
        findings.append(Finding("medium", "whale", f"Tek bir cüzdan arzın %{largest:.1f}'ini tutuyor"))

    if creator_pct > 10:
        findings.append(Finding("high", "creator_high", f"Geliştirici arzın %{creator_pct:.1f}'ini tutuyor"))
    elif creator_pct > 5:
        findings.append(Finding("medium", "creator_mid", f"Geliştirici arzın %{creator_pct:.1f}'ini tutuyor"))

    if burned:
        findings.append(Finding("info", "burned", f"Arzın %{pct(burned):.1f}'i yakılmış"))
    return data, findings


async def check_holders(
    blockscout: Blockscout | None, token: str, total_supply: int, exclude: set[str], creator: str | None
) -> tuple[dict, list[Finding]]:
    holders = await blockscout.token_holders(token) if blockscout else None
    if holders is None:
        return {}, [Finding("low", "holders_unknown", "Holder verisi alınamadı (explorer yanıt vermedi)")]
    if not holders:
        return {}, [Finding("low", "holders_empty", "Explorer henüz holder listesi oluşturmamış")]
    return analyse_holders(holders, total_supply, exclude, creator)
