"""Finds newly created DEX pools on Robinhood Chain by polling event logs.

Pools are matched by event signature only, so every Uniswap V2/V3/V4 deployment
and fork (including launchpads that graduate tokens into a Uniswap-style pool)
is covered without hard-coding factory addresses.
"""

import asyncio
import logging
from dataclasses import dataclass

from eth_abi import decode
from eth_utils import keccak, to_checksum_address

from .rpc import RpcClient

log = logging.getLogger(__name__)

TOPIC_V2_PAIR_CREATED = "0x" + keccak(text="PairCreated(address,address,address,uint256)").hex()
TOPIC_V3_POOL_CREATED = "0x" + keccak(text="PoolCreated(address,address,uint24,int24,address)").hex()
TOPIC_V4_INITIALIZE = "0x" + keccak(
    text="Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)"
).hex()
POOL_TOPICS = [TOPIC_V2_PAIR_CREATED, TOPIC_V3_POOL_CREATED, TOPIC_V4_INITIALIZE]

ZERO_ADDRESS = "0x" + "0" * 40


@dataclass
class NewPool:
    dex: str  # "v2", "v3" or "v4"
    factory: str  # emitting factory (V4: the PoolManager)
    token: str  # the newly listed token
    quote: str  # WETH / native ETH / configured quote token
    pool: str  # pair/pool address; V4: the pool id
    block: int
    tx_hash: str
    fee: int | None = None
    hooks: str | None = None  # V4 only


def _topic_address(topic: str) -> str:
    return to_checksum_address("0x" + topic[-40:])


def parse_log(entry: dict, quote_tokens: set[str]) -> NewPool | None:
    """Turn a pool-creation log into a NewPool, or None if it is not a new-token/quote pool."""
    topics = entry.get("topics") or []
    if not topics:
        return None
    topic0 = topics[0].lower()
    data = bytes.fromhex(entry["data"][2:])
    fee = hooks = None
    try:
        if topic0 == TOPIC_V2_PAIR_CREATED and len(topics) >= 3:
            dex = "v2"
            token0, token1 = _topic_address(topics[1]), _topic_address(topics[2])
            pool = to_checksum_address(decode(["address", "uint256"], data)[0])
        elif topic0 == TOPIC_V3_POOL_CREATED and len(topics) >= 4:
            dex = "v3"
            token0, token1 = _topic_address(topics[1]), _topic_address(topics[2])
            fee = int(topics[3], 16)
            pool = to_checksum_address(decode(["int24", "address"], data)[1])
        elif topic0 == TOPIC_V4_INITIALIZE and len(topics) >= 4:
            dex = "v4"
            pool = topics[1]
            token0, token1 = _topic_address(topics[2]), _topic_address(topics[3])
            fee, _spacing, hooks_addr, _price, _tick = decode(
                ["uint24", "int24", "address", "uint160", "int24"], data
            )
            hooks = to_checksum_address(hooks_addr)
        else:
            return None
    except Exception as exc:  # malformed or spoofed log
        log.debug("unparseable pool log %s: %s", entry.get("transactionHash"), exc)
        return None

    q0, q1 = token0.lower() in quote_tokens, token1.lower() in quote_tokens
    if q0 == q1:  # both quotes (e.g. WETH/USDC) or neither: not a fresh token listing
        return None
    token, quote = (token1, token0) if q0 else (token0, token1)
    return NewPool(
        dex=dex,
        factory=to_checksum_address(entry["address"]),
        token=token,
        quote=quote,
        pool=pool,
        block=int(entry["blockNumber"], 16),
        tx_hash=entry.get("transactionHash", ""),
        fee=fee,
        hooks=hooks,
    )


async def is_genuine(rpc: RpcClient, pool: NewPool, allowlist: list[str]) -> bool:
    """Reject logs emitted by contracts pretending to be factories."""
    if allowlist:
        return pool.factory.lower() in allowlist
    if pool.dex == "v4":
        return True  # nothing cheap to cross-check; use FACTORY_ALLOWLIST to pin the PoolManager
    result = await rpc.try_call_fn(pool.pool, "factory()", ["address"])
    return bool(result) and result[0].lower() == pool.factory.lower()


class PoolWatcher:
    """Polls eth_getLogs and yields new pools, remembering the last scanned block."""

    def __init__(self, rpc: RpcClient, settings, storage):
        self.rpc = rpc
        self.settings = settings
        self.storage = storage

    async def _start_block(self) -> int:
        saved = self.storage.get_state("last_block")
        if saved is not None:
            return int(saved) + 1
        head = await self.rpc.block_number()
        return max(0, head - self.settings.start_lookback_blocks)

    async def run(self, on_pool):
        next_block = await self._start_block()
        log.info("watching for new pools from block %d", next_block)
        while True:
            try:
                head = await self.rpc.block_number()
                while next_block <= head:
                    to_block = min(head, next_block + self.settings.max_block_range - 1)
                    logs = await self.rpc.get_logs(next_block, to_block, [POOL_TOPICS])
                    for entry in logs:
                        pool = parse_log(entry, self.settings.quote_tokens)
                        if pool and await is_genuine(self.rpc, pool, self.settings.factory_allowlist):
                            await on_pool(pool)
                    self.storage.set_state("last_block", str(to_block))
                    next_block = to_block + 1
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("pool polling failed; will retry")
            await asyncio.sleep(self.settings.poll_interval)
