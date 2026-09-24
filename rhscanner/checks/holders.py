"""Supply distribution: whale concentration, creator share, burned supply.

Holders are found from the token's Transfer logs over plain RPC (the public
Blockscout API sits behind a Cloudflare challenge that blocks servers), and
the largest candidates are confirmed with live balanceOf calls.
"""

import logging
from collections import defaultdict

from ..rpc import RpcClient
from . import DEAD_ADDRESSES, Finding

log = logging.getLogger(__name__)

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
MAX_TRANSFER_LOGS = 60_000
MAX_FAILED_QUERIES = 40
TOP_CANDIDATES = 25
WINDOW_BLOCKS = 2_000_000  # ~2.3 days of Robinhood Chain blocks


def analyse_holders(
    holders: list[dict], total_supply: int, exclude: set[str], creator: str | None
) -> tuple[dict, list[Finding]]:
    """holders: Blockscout items ({"address": {"hash", "is_contract"}, "value"})."""
    findings: list[Finding] = []
    if not total_supply:
        return {}, [Finding("medium", "no_supply", "Toplam arz okunamadı")]

    exclude = {a.lower() for a in exclude}
    burned = contracts = 0
    wallets: list[tuple[str, int]] = []
    for item in holders:
        addr = (item.get("address") or {}).get("hash", "").lower()
        value = int(item.get("value") or 0)
        if addr in DEAD_ADDRESSES:
            burned += value
        elif addr in exclude:
            continue
        elif (item.get("address") or {}).get("is_contract"):
            # Bonding curves, lockers, pools of other DEXes: not a person who can dump.
            contracts += value
        else:
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
        "contracts_pct": round(pct(contracts), 2),
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
    if contracts:
        findings.append(Finding("info", "in_contracts", f"Arzın %{pct(contracts):.1f}'i kontratlarda (curve/havuz/kilit)"))
    return data, findings


async def _transfer_logs(rpc: RpcClient, token: str, from_block: int, to_block: int, budget: dict) -> list[dict]:
    """All Transfer logs in range, splitting it whenever the node caps or times out the query.

    budget["logs"] bounds how many logs are collected and budget["failures"] how
    many refused queries are tolerated (a node that only serves tiny ranges
    would otherwise be asked thousands of times).
    """
    if budget["logs"] <= 0 or budget["failures"] <= 0:
        return []
    try:
        logs = await rpc.get_logs(from_block, to_block, [TRANSFER_TOPIC], address=token, retries=0)
    except Exception as exc:  # usually "logs matched by query exceeds limit"
        budget["failures"] -= 1
        if to_block - from_block < 1000:
            log.debug("transfer logs for %s failed: %s", token, exc)
            return []
        mid = (from_block + to_block) // 2
        # Newest half first, so the budget is spent on current holders.
        newer = await _transfer_logs(rpc, token, mid + 1, to_block, budget)
        return await _transfer_logs(rpc, token, from_block, mid, budget) + newer
    budget["logs"] -= len(logs)
    return logs


async def recent_transfer_logs(rpc: RpcClient, token: str, head: int, lookback_blocks: int) -> list[dict]:
    """Walk back from head in windows; stop at the first empty window before the token's activity."""
    budget = {"logs": MAX_TRANSFER_LOGS, "failures": MAX_FAILED_QUERIES}
    logs: list[dict] = []
    hi, floor = head, max(0, head - lookback_blocks)
    while hi > floor and budget["logs"] > 0 and budget["failures"] > 0:
        lo = max(floor, hi - WINDOW_BLOCKS + 1)
        window = await _transfer_logs(rpc, token, lo, hi, budget)
        if not window and logs:
            break  # nothing earlier: we reached the token's creation
        logs = window + logs
        hi = lo - 1
    return logs


async def collect_holders(rpc: RpcClient, token: str, lookback_blocks: int) -> list[dict]:
    """Blockscout-shaped holder items ({"address": {"hash", "is_contract"}, "value"})."""
    head = await rpc.block_number()
    logs = await recent_transfer_logs(rpc, token, head, lookback_blocks)
    received: dict[str, int] = defaultdict(int)
    for entry in logs:
        if len(entry.get("topics") or []) < 3:
            continue
        amount = int(entry["data"], 16) if entry["data"] not in ("0x", "") else 0
        received["0x" + entry["topics"][2][-40:]] += amount
        received["0x" + entry["topics"][1][-40:]] -= amount
    candidates = sorted(received, key=received.get, reverse=True)[:TOP_CANDIDATES]
    items = []
    for addr in candidates:
        balance = await rpc.try_call_fn(token, "balanceOf(address)", ["uint256"], ["address"], [addr])
        if not balance or not balance[0]:
            continue
        code = await rpc.get_code(addr) if addr not in DEAD_ADDRESSES else "0x"
        is_contract = len(code) > 2 and not code.lower().startswith("0xef0100")  # EIP-7702 wallets are people
        items.append({"address": {"hash": addr, "is_contract": is_contract}, "value": str(balance[0])})
    return items


async def check_holders(
    rpc: RpcClient, token: str, total_supply: int, exclude: set[str], creator: str | None, lookback_blocks: int
) -> tuple[dict, list[Finding]]:
    try:
        holders = await collect_holders(rpc, token, lookback_blocks)
    except Exception as exc:
        log.warning("holder scan for %s failed: %s", token, exc)
        holders = None
    if not holders:
        return {}, [Finding("low", "holders_unknown", "Holder verisi alınamadı")]
    return analyse_holders(holders, total_supply, exclude, creator)
