"""How widely each Uniswap V4 hook is used on Robinhood Chain.

A hook runs custom code on every swap of its pools, so it could block sells.
Hooks cannot be named from the chain (they expose no name()), but a hook shared
by hundreds of launchpad pools is far less suspicious than one used by a single
pool. The registry counts hooks in recent Initialize events and refreshes the
counts in the background.
"""

import logging
import time
from collections import Counter

from .rpc import RpcClient

log = logging.getLogger(__name__)

TOPIC_V4_INITIALIZE = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
ZERO = "0x0000000000000000000000000000000000000000"
EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

# Hooks identified from launchpad documentation (lowercased).
NAMED_HOOKS = {
    "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544": "Pons (Doppler) launchpad",
}

# Pools per hook over ~3 days (2.6M blocks) as measured on 2026-09-24; used until
# the first background refresh completes.
SEED_COUNTS = {
    "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544": 10172,
    "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044": 351,
    "0x4eb1976978756bd56802d8162f2271844924e0cc": 321,
    "0x0310cfebe1d7a69f2414f6595bbe9d17c5342acc": 81,
    "0x5bea51a486a6a85e4f5c86eaad9f61851aaf0044": 80,
    "0x9756a82b4901acdbb5345bb35b21b5b79b2d60cc": 69,
    "0xe693a6978cae40520c1aa040ab0ff2d44454f8cc": 65,
    "0x48b8f6ad3a1b4aa477314c9a23035b8f84dde8cc": 46,
}

COMMON_MIN_POOLS = 40
SCAN_BLOCKS = 2_600_000  # ~3 days at ~10 blocks/s
SCAN_STEP = 200_000
REFRESH_SECONDS = 6 * 3600


class HookRegistry:
    def __init__(self, counts: dict[str, int] | None = None):
        self.counts: dict[str, int] = dict(SEED_COUNTS if counts is None else counts)
        self.refreshed_at = 0.0
        self._upgradeable: dict[str, bool] = {}

    def pools(self, hook: str) -> int:
        return self.counts.get(hook.lower(), 0)

    async def is_upgradeable(self, rpc: RpcClient, hook: str) -> bool:
        hook = hook.lower()
        if hook not in self._upgradeable:
            try:
                slot = await rpc.get_storage_at(hook, EIP1967_IMPL_SLOT)
                self._upgradeable[hook] = bool(slot) and int(slot, 16) != 0
            except Exception:
                return False
        return self._upgradeable[hook]

    async def refresh(self, rpc: RpcClient, pool_manager: str):
        head = await rpc.block_number()
        counts: Counter[str] = Counter()
        for lo in range(max(0, head - SCAN_BLOCKS), head + 1, SCAN_STEP):
            logs = await rpc.get_logs(lo, min(head, lo + SCAN_STEP - 1), [TOPIC_V4_INITIALIZE], address=pool_manager)
            for entry in logs:
                counts["0x" + entry["data"][2 + 128: 2 + 192][-40:]] += 1
        counts.pop(ZERO, None)
        self.counts = dict(counts)
        self.refreshed_at = time.time()
        log.info("hook registry refreshed: %d hooks, top %s", len(counts), counts.most_common(3))

    async def run(self, rpc: RpcClient, pool_manager: str):
        import asyncio

        while True:
            try:
                await self.refresh(rpc, pool_manager)
                await asyncio.sleep(REFRESH_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("hook registry refresh failed (%s); retrying in 10 min", exc)
                await asyncio.sleep(600)


REGISTRY = HookRegistry()
