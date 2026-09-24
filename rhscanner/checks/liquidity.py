"""Liquidity depth and whether the liquidity can be pulled (LP burn/lock)."""

from ..hooks import COMMON_MIN_POOLS, NAMED_HOOKS, REGISTRY, HookRegistry
from ..rpc import RpcClient
from ..sources import Blockscout
from . import DEAD_ADDRESSES, Finding

ZERO = "0x0000000000000000000000000000000000000000"
TOPIC_V4_INITIALIZE = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"

async def lookup_v4_hooks(rpc: RpcClient, pool_manager: str, pool_id: str, lookback_blocks: int) -> str | None:
    """Find a V4 pool's hook address from its Initialize event."""
    head = await rpc.block_number()
    try:
        logs = await rpc.get_logs(
            max(0, head - lookback_blocks), head, [TOPIC_V4_INITIALIZE, pool_id], address=pool_manager, retries=1
        )
    except Exception:
        return None
    if not logs:
        return None
    data = logs[0]["data"]
    return "0x" + data[2 + 64 * 2: 2 + 64 * 3][-40:]  # third word: hooks


async def _hook_finding(rpc: RpcClient, registry: HookRegistry, hook: str, data: dict) -> Finding:
    pools = registry.pools(hook)
    data["hook_pools"] = pools
    upgradeable = await registry.is_upgradeable(rpc, hook)
    note = " · yükseltilebilir (sahibi kodu değiştirebilir)" if upgradeable else ""
    if hook in NAMED_HOOKS:
        data["launchpad"] = NAMED_HOOKS[hook]
        return Finding("info", "v4_known_hook", f"Launchpad: {NAMED_HOOKS[hook]}{note}")
    if pools >= COMMON_MIN_POOLS:
        data["launchpad"] = f"yaygın launchpad hook'u ({pools} havuz)"
        return Finding(
            "low", "v4_common_hook", f"Yaygın launchpad hook'u: son 3 günde {pools} havuzda kullanılmış{note}"
        )
    return Finding(
        "high" if upgradeable else "medium", "v4_hooks",
        f"Nadir V4 hook'u (son 3 günde {pools} havuz) — her swap'ta özel kod çalışıyor{note}",
    )


def _liquidity_findings(eth: float) -> list[Finding]:
    if eth < 0.5:
        return [Finding("high", "liq_low", f"Likidite çok düşük: {eth:.3f} ETH")]
    if eth < 2:
        return [Finding("medium", "liq_mid", f"Likidite düşük: {eth:.2f} ETH")]
    return [Finding("good", "liq_ok", f"Likidite: {eth:.2f} ETH")]


async def check_liquidity(
    rpc: RpcClient, blockscout: Blockscout | None, pool: dict, weth: str,
    pool_manager: str | None = None, lookback_blocks: int = 30_000_000, registry: HookRegistry = REGISTRY,
) -> tuple[dict, list[Finding]]:
    """pool: {"dex", "pool", "token", "quote", "hooks"}."""
    dex, address = pool["dex"], pool["pool"]
    quote_is_eth = pool["quote"].lower() in (weth.lower(), ZERO)
    data: dict = {"dex": dex}
    findings: list[Finding] = []

    if dex == "v4":
        hooks = pool.get("hooks")
        if hooks is None and pool_manager:
            hooks = await lookup_v4_hooks(rpc, pool_manager, address, lookback_blocks)
        if hooks is None:
            findings.append(Finding("low", "v4_hooks_unknown", "V4 havuzunun hook'u tespit edilemedi"))
        else:
            hooks = hooks.lower()
            data["hooks"] = hooks
            if hooks != ZERO:
                findings.append(await _hook_finding(rpc, registry, hooks, data))
        findings.append(Finding("low", "v4_lp_unknown", "V4 havuzu: LP kilidi doğrulanamadı"))
        return data, findings

    if quote_is_eth:
        balance = await rpc.try_call_fn(weth, "balanceOf(address)", ["uint256"], ["address"], [address])
        if balance:
            data["liquidity_eth"] = balance[0] / 1e18
            findings += _liquidity_findings(data["liquidity_eth"])

    if dex == "v3":
        findings.append(Finding("medium", "v3_lp_unknown", "V3 havuzu: LP kilidi doğrulanamadı (NFT pozisyon)"))
        return data, findings

    supply = await rpc.try_call_fn(address, "totalSupply()", ["uint256"])
    if not supply or not supply[0]:
        return data, findings
    burned = 0
    for dead in DEAD_ADDRESSES:
        bal = await rpc.try_call_fn(address, "balanceOf(address)", ["uint256"], ["address"], [dead])
        burned += bal[0] if bal else 0
    burned_pct = 100.0 * burned / supply[0]
    data["lp_burned_pct"] = round(burned_pct, 2)
    if burned_pct >= 95:
        findings.append(Finding("good", "lp_burned", f"LP token'ların %{burned_pct:.0f}'i yakılmış — likidite çekilemez"))
        return data, findings

    # Not burned: a contract holding the LP is probably a locker, an EOA can rug at will.
    top_is_contract = None
    if blockscout:
        holders = await blockscout.token_holders(address)
        if holders:
            top = max(holders, key=lambda h: int(h.get("value") or 0))
            top_is_contract = bool((top.get("address") or {}).get("is_contract"))
            data["lp_top_holder"] = (top.get("address") or {}).get("hash")
    if top_is_contract:
        findings.append(Finding(
            "medium", "lp_in_contract",
            f"LP'nin sadece %{burned_pct:.0f}'i yakılmış; kalanı bir kontratta (kilit olabilir, kontrol edin)",
        ))
    else:
        findings.append(Finding(
            "high", "lp_unlocked",
            f"LP'nin sadece %{burned_pct:.0f}'i yakılmış — geliştirici likiditeyi çekebilir (rugpull riski)",
        ))
    return data, findings
