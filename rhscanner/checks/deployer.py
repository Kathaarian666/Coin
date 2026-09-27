"""The launcher's track record: how many coins it made before and how they ended.

Serial launchers behave like bots (launch, dump, repeat). Pons V2's factory
emits one event per launch with the token and the launcher as indexed topics.
The bot keeps those in a local index (launches.py); without it (CLI) the
launcher's history is asked from the node per block window, which is slow.
Tokens from other launchpads are skipped (no verdict).
"""

import logging

from ..rpc import RpcClient
from . import Finding

log = logging.getLogger(__name__)

PONS_V2_FACTORY = "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"
# event emitted per launch: topic1 = token, topic2 = its curve/pool, topic3 = launcher
PONS_V2_LAUNCH = "0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607"
LOOKBACK_BLOCKS = 20_000_000  # ~23 days
WINDOW_BLOCKS = 4_000_000
MIN_WINDOW_BLOCKS = 1_000_000
DAY_BLOCKS = 864_000  # ~10 blocks/s
ALIVE_LIQUIDITY_USD = 5_000
MAX_CHECKED = 30


def _topic(address: str) -> str:
    return "0x" + address.lower()[2:].rjust(64, "0")


async def _window(rpc: RpcClient, topics: list, lo: int, hi: int) -> tuple[list[dict], int]:
    """Logs of one block window; a window the node times out on is split in halves down to MIN_WINDOW_BLOCKS."""
    try:
        return await rpc.get_logs(lo, hi, topics, address=PONS_V2_FACTORY, retries=1), 0
    except Exception as exc:  # one slow window should not sink the whole check
        if hi - lo + 1 <= MIN_WINDOW_BLOCKS:
            log.debug("launch history window %d-%d failed: %s", lo, hi, exc)
            return [], 1
    mid = (lo + hi) // 2
    older, failed_old = await _window(rpc, topics, lo, mid)
    newer, failed_new = await _window(rpc, topics, mid + 1, hi)
    return older + newer, failed_old + failed_new


async def launches_by(rpc: RpcClient, launcher: str, head: int) -> tuple[list[dict], int]:
    """The launcher's launch events over the lookback, plus how many block windows failed."""
    topics = [PONS_V2_LAUNCH, None, None, _topic(launcher)]
    logs: list[dict] = []
    failed = 0
    for hi in range(head, head - LOOKBACK_BLOCKS, -WINDOW_BLOCKS):
        found, bad = await _window(rpc, topics, max(0, hi - WINDOW_BLOCKS + 1), hi)
        logs += found
        failed += bad
    return logs, failed


async def launcher_of(rpc: RpcClient, token: str, launch_block: int) -> str | None:
    """The launcher from the factory's launch event in the token's first block (None: not a Pons V2 launch)."""
    logs = await rpc.get_logs(launch_block, launch_block, [PONS_V2_LAUNCH, _topic(token)],
                              address=PONS_V2_FACTORY, retries=2)
    for entry in logs:
        topics = entry.get("topics") or []
        if len(topics) >= 4:
            return "0x" + topics[3][-40:]
    return None


async def check_deployer(rpc: RpcClient, dexscreener, token: str, launch_block: int | None,
                         index=None) -> tuple[dict, list[Finding]]:
    """index: a launches.LaunchIndex (bot mode); without one the history is asked from the node."""
    launcher = index.launcher_of(token) if index else None
    if not launcher and launch_block is not None:
        launcher = await launcher_of(rpc, token, launch_block)
    if not launcher:
        return {}, []
    head = await rpc.block_number()
    if index:
        tokens = index.launches_by(launcher)
        failed = 0 if index.complete(head) else 1  # backfill still running
    else:
        logs, failed = await launches_by(rpc, launcher, head)
        tokens = {("0x" + e["topics"][1][-40:]).lower(): int(e["blockNumber"], 16) for e in logs}
    previous = {t: b for t, b in tokens.items() if t != token.lower()}
    last_day = sum(1 for b in previous.values() if b >= head - DAY_BLOCKS)
    data: dict = {"launcher": launcher, "previous_launches": len(previous), "launches_24h": last_day}

    if failed:
        data["partial"] = True  # counts are a lower bound
    findings: list[Finding] = []
    if not previous:
        return data, [] if failed else [Finding("info", "first_launch", "Geliştiricinin ilk Pons coini")]

    # the count alone is a weaker signal than how the earlier coins ended (launcher_dead_coins)
    if len(previous) >= 10:
        findings.append(Finding("medium", "serial_launcher",
                                f"Seri coin çıkarıcı: son ~3 haftada {len(previous)} coin daha çıkarmış ({last_day} tanesi son 24 saatte)"))
    elif len(previous) >= 3:
        findings.append(Finding("low", "repeat_launcher", f"Geliştirici son ~3 haftada {len(previous)} coin daha çıkarmış"))

    if dexscreener:
        recent = sorted(previous, key=previous.get, reverse=True)[:MAX_CHECKED]
        pairs = []
        for i in range(0, len(recent), 30):
            pairs += await dexscreener.tokens(recent[i: i + 30])
        best: dict[str, dict] = {}
        for p in pairs:
            base = (p.get("baseToken") or {}).get("address", "").lower()
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if base in previous and liq >= (best.get(base) or {}).get("liq", -1):
                best[base] = {"liq": liq, "fdv": p.get("fdv") or 0}
        alive = sum(1 for t in recent if (best.get(t) or {}).get("liq", 0) >= ALIVE_LIQUIDITY_USD)
        top_fdv = max((v["fdv"] for v in best.values()), default=0)
        data.update(checked=len(recent), alive=alive, best_previous_fdv=top_fdv)
        dead_share = 1 - alive / len(recent)
        if len(recent) >= 3 and dead_share >= 0.8:
            findings.append(Finding("high", "launcher_dead_coins",
                                    f"Geliştiricinin önceki {len(recent)} coininin {len(recent) - alive} tanesi ölü (likidite < ${ALIVE_LIQUIDITY_USD:,})"))
        if top_fdv >= 1_000_000:
            findings.append(Finding("good", "launcher_hit", f"Geliştiricinin önceki bir coini ${top_fdv / 1e6:.1f}M FDV'ye ulaşmış"))
    return data, findings
