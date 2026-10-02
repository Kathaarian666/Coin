"""Who got in at launch: creator (dev), same-transaction bundles and first-seconds snipers.

Research on Solana launchpads (MemeTrans, GMGN defaults) finds that high-risk
launches carry 17-19 points more supply in dev + sniper hands and that bundled
wallets often hold a third of the supply. Everything here is derived from the
token's Transfer logs (already fetched for the holder scan) plus a few calls.
"""

import logging
import time

from ..rpc import RpcClient
from . import DEAD_ADDRESSES, Finding

log = logging.getLogger(__name__)

ZERO = "0x0000000000000000000000000000000000000000"
ENTRY_POINT = "0x4337084d9e255ff0702461cf8895ce9e3b5ff108"  # ERC-4337 v0.8 on Robinhood Chain
USER_OPERATION_EVENT = "0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f"
SNIPER_BLOCKS = 30  # ~3 s of Robinhood Chain blocks after the mint
MAX_EARLY_WALLETS = 30


def _addr(topic: str) -> str:
    return "0x" + topic[-40:]


def _amount(entry: dict) -> int:
    return int(entry["data"], 16) if entry.get("data") not in (None, "0x", "") else 0


async def _tx_sender(rpc: RpcClient, tx_hash: str) -> str | None:
    """The account that launched: the tx sender, or the smart account for ERC-4337 launches."""
    tx = await rpc.request("eth_getTransactionByHash", [tx_hash])
    if not tx:
        return None
    if (tx.get("to") or "").lower() != ENTRY_POINT:
        return tx["from"].lower()
    receipt = await rpc.request("eth_getTransactionReceipt", [tx_hash])
    for entry in (receipt or {}).get("logs", []):
        topics = entry.get("topics") or []
        if entry["address"].lower() == ENTRY_POINT and topics and topics[0] == USER_OPERATION_EVENT:
            return _addr(topics[2])
    return None


async def _is_wallet(rpc: RpcClient, address: str) -> bool:
    code = await rpc.get_code(address)
    return len(code) <= 2 or code.lower().startswith("0xef0100")  # EOA or EIP-7702 wallet


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_TOPIC = "0x" + "0" * 64


async def launch_logs(rpc: RpcClient, token: str, lookback_blocks: int) -> list[dict]:
    """Transfer logs of the launch: the mint(s) and the first seconds after it.

    Mints are found with a from=0x0 filter, which matches a handful of logs even
    for tokens with hundreds of thousands of transfers.
    """
    head = await rpc.block_number()
    mints = await rpc.get_logs(max(0, head - lookback_blocks), head, [TRANSFER_TOPIC, ZERO_TOPIC], address=token)
    if not mints:
        return []
    first = int(mints[0]["blockNumber"], 16)
    return await rpc.get_logs(first, first + SNIPER_BLOCKS, [TRANSFER_TOPIC], address=token)


async def analyse_launch(
    rpc: RpcClient, token: str, logs: list[dict], total_supply: int, exclude: set[str]
) -> tuple[dict, list[Finding]]:
    """logs: Transfer logs from the launch on, oldest first (see launch_logs)."""
    mints = [e for e in logs if len(e.get("topics") or []) >= 3 and _addr(e["topics"][1]) == ZERO]
    if not mints or not total_supply:
        return {}, []
    mint = mints[0]
    mint_block = int(mint["blockNumber"], 16)
    mint_tx = mint["transactionHash"]
    exclude = {a.lower() for a in exclude} | DEAD_ADDRESSES | {token.lower()}
    minted_to = {_addr(e["topics"][2]) for e in mints if e["transactionHash"] == mint_tx}

    data: dict = {"launch_block": mint_block}
    try:
        stamp = await rpc.block_timestamp(mint_block)
        data["age_min"] = round((time.time() - stamp) / 60, 1)
    except Exception:
        pass

    creator = None
    try:
        creator = await _tx_sender(rpc, mint_tx)
    except Exception as exc:
        log.debug("launch sender lookup failed for %s: %s", token, exc)
    data["creator"] = creator

    # Tokens received per wallet in the launch transaction (dev buy + bundles) and just after it.
    bundle: dict[str, int] = {}
    early: dict[str, int] = {}
    creator_initial = 0
    for entry in logs:
        topics = entry.get("topics") or []
        if len(topics) < 3:
            continue
        block = int(entry["blockNumber"], 16)
        if block > mint_block + SNIPER_BLOCKS:
            break
        to, frm = _addr(topics[2]), _addr(topics[1])
        if frm == ZERO or to in exclude or to in minted_to:
            continue
        amount = _amount(entry)
        if to == creator:
            creator_initial += amount
        elif entry["transactionHash"] == mint_tx:
            bundle[to] = bundle.get(to, 0) + amount
        else:
            early[to] = early.get(to, 0) + amount

    async def current_share(wallets) -> float:
        total = 0
        for wallet in list(wallets)[:MAX_EARLY_WALLETS]:
            if not await _is_wallet(rpc, wallet):
                continue  # routers, pools and curves pass tokens through
            balance = await rpc.try_call_fn(token, "balanceOf(address)", ["uint256"], ["address"], [wallet])
            total += balance[0] if balance else 0
        return 100.0 * total / total_supply

    pct = lambda v: 100.0 * v / total_supply  # noqa: E731
    findings: list[Finding] = []
    if creator:
        balance = await rpc.try_call_fn(token, "balanceOf(address)", ["uint256"], ["address"], [creator])
        dev_now = pct(balance[0]) if balance else 0.0
        dev_initial = pct(creator_initial)
        data.update(dev_initial_pct=round(dev_initial, 2), dev_pct=round(dev_now, 2))
        if dev_now > 10:
            findings.append(Finding("high", "dev_holds", f"Geliştirici hâlâ arzın %{dev_now:.1f}'ini tutuyor"))
        elif dev_now > 5:
            findings.append(Finding("medium", "dev_holds_mid", f"Geliştirici arzın %{dev_now:.1f}'ini tutuyor"))
        if dev_initial >= 1 and dev_now < dev_initial / 2:
            findings.append(Finding(
                "medium", "dev_sold", f"Geliştirici ilk aldığının yarısından fazlasını sattı (%{dev_initial:.1f} → %{dev_now:.1f})"
            ))

    data["bundle_wallets"] = len(bundle)
    data["sniper_wallets"] = len(early)
    bundle_pct = await current_share(bundle) if bundle else 0.0
    sniper_pct = await current_share(early) if early else 0.0
    data.update(bundle_pct=round(bundle_pct, 2), sniper_pct=round(sniper_pct, 2))
    if bundle_pct > 10:
        findings.append(Finding(
            "high", "bundled", f"Lansmanla aynı işlemde alan {len(bundle)} cüzdan arzın %{bundle_pct:.1f}'ini tutuyor (bundle)"
        ))
    if sniper_pct > 25:
        findings.append(Finding("high", "snipers_high", f"İlk ~3 saniyede alanlar hâlâ arzın %{sniper_pct:.1f}'ini tutuyor"))
    elif sniper_pct > 10:
        findings.append(Finding("medium", "snipers_mid", f"İlk ~3 saniyede alanlar arzın %{sniper_pct:.1f}'ini tutuyor"))
    if not findings:
        findings.append(Finding("good", "launch_clean", "Lansman temiz: dev/bundle/sniper payı düşük"))
    return data, findings
