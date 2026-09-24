"""Exit signals for alerted tokens.

A price drop alone is deliberately NOT an exit signal: most runners pull back
hard and recover. What matters is who is selling and whether the market under
the token is being taken away:

  strong  (🔴 ÇIK)    the dev or a top holder dumping, or liquidity being pulled
  warning (🟠 DİKKAT) Fomo buying has stopped and turned into selling, or the
                      whole market is selling in a wave

When the price is down but none of these hold, the follow-up says the dip
looks healthy (buyers still coming, dev and whales holding, pool intact).
"""

from dataclasses import dataclass, field

STRONG, WARNING = "strong", "warning"


@dataclass
class Snapshot:
    """What an exit check compares against: taken at alert time, and again at each check."""
    dev_pct: float | None = None
    top_wallets: dict[str, float] = field(default_factory=dict)  # wallet -> % of supply
    liquidity_base: float | None = None  # token side of the pool
    liquidity_quote: float | None = None  # ETH/USDG/stock side of the pool
    price_usd: float | None = None


def evaluate_exit(then: Snapshot, now: Snapshot, fomo_5m: dict, market_m5: dict) -> list[tuple[str, str]]:
    """Returns [(level, reason)], strongest first; empty when nothing says 'get out'."""
    reasons: list[tuple[str, str]] = []

    if then.dev_pct is not None and now.dev_pct is not None and then.dev_pct >= 1 and now.dev_pct <= then.dev_pct / 2:
        reasons.append((STRONG, f"Geliştirici satıyor: arzın %{then.dev_pct:.1f}'i → %{now.dev_pct:.1f}"))

    for wallet, pct in then.top_wallets.items():
        current = now.top_wallets.get(wallet)
        if pct >= 3 and current is not None and current <= pct / 2:
            reasons.append((STRONG, f"Büyük cüzdan satıyor: {wallet[:8]}… %{pct:.1f} → %{current:.1f}"))

    # A withdrawal shrinks both sides of the pool; trading moves them in opposite directions.
    if then.liquidity_base and then.liquidity_quote and now.liquidity_base is not None and now.liquidity_quote is not None:
        base_left = now.liquidity_base / then.liquidity_base
        quote_left = now.liquidity_quote / then.liquidity_quote
        if base_left <= 0.6 and quote_left <= 0.6:
            reasons.append((STRONG, f"Likidite çekiliyor: havuzun iki tarafı da %{(1 - max(base_left, quote_left)) * 100:.0f}+ azaldı"))

    buyers, sellers = fomo_5m.get("buyers", 0), fomo_5m.get("sellers", 0)
    buy_usd, sell_usd = fomo_5m.get("buy_usd", 0), fomo_5m.get("sell_usd", 0)
    if buyers <= 1 and sellers >= 3 and sell_usd >= max(100, 2 * buy_usd):
        reasons.append((WARNING, f"Fomo'da alım bitti, satış başladı: son 5 dk {buyers} alıcı / {sellers} satıcı"))

    m5_buys, m5_sells = market_m5.get("buys") or 0, market_m5.get("sells") or 0
    if m5_sells >= 15 and m5_sells >= 3 * max(m5_buys, 1):
        reasons.append((WARNING, f"Piyasada satış dalgası: son 5 dk {m5_buys} alım / {m5_sells} satış"))

    return sorted(reasons, key=lambda r: r[0] != STRONG)


def exit_level(reasons: list[tuple[str, str]]) -> str | None:
    if any(level == STRONG for level, _ in reasons):
        return STRONG
    return WARNING if reasons else None


def breakeven_multiple(position_usd: float, fee_pct: float = 0.5, fee_min_usd: float = 0.95) -> float | None:
    """Price multiple needed to get the position back after a buy and a sell fee.

    Buy fee comes out of the position; the sell fee is charged on the proceeds.
    """
    buy_fee = max(fee_min_usd, position_usd * fee_pct / 100)
    invested = position_usd - buy_fee
    if invested <= 0:
        return None
    multiple = 1.0
    for _ in range(20):  # the sell fee depends on the proceeds, so iterate
        proceeds = multiple * invested
        sell_fee = max(fee_min_usd, proceeds * fee_pct / 100)
        multiple = (position_usd + sell_fee) / invested
    return round(multiple, 2)
