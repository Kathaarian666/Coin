"""Minimal async JSON-RPC client with retries and a request-rate cap."""

import asyncio
import itertools
import logging
import time

import httpx
from eth_abi import decode, encode
from eth_utils import function_signature_to_4byte_selector

log = logging.getLogger(__name__)


class RpcError(Exception):
    """The node answered with a JSON-RPC error (e.g. the call reverted)."""


class RateLimiter:
    def __init__(self, max_per_second: float):
        self.interval = 1.0 / max_per_second if max_per_second > 0 else 0.0
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        if not self.interval:
            return
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self.interval


class RpcClient:
    def __init__(self, url: str, max_rps: float = 8.0, client: httpx.AsyncClient | None = None):
        self.url = url
        self.http = client or httpx.AsyncClient(timeout=20)
        self.limiter = RateLimiter(max_rps)
        self._ids = itertools.count(1)

    async def close(self):
        await self.http.aclose()

    async def request(self, method: str, params: list, retries: int = 4):
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        delay = 1.0
        for attempt in range(retries + 1):
            await self.limiter.wait()
            try:
                resp = await self.http.post(self.url, json=payload)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
                resp.raise_for_status()
                body = resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                if attempt == retries:
                    raise
                log.warning("RPC %s failed (%s), retrying in %.0fs", method, exc, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if "error" in body:
                raise RpcError(f"{method}: {body['error']}")
            return body["result"]

    async def block_number(self) -> int:
        return int(await self.request("eth_blockNumber", []), 16)

    async def get_logs(self, from_block: int, to_block: int, topics: list) -> list[dict]:
        return await self.request(
            "eth_getLogs", [{"fromBlock": hex(from_block), "toBlock": hex(to_block), "topics": topics}]
        )

    async def get_code(self, address: str) -> str:
        return await self.request("eth_getCode", [address, "latest"])

    async def get_storage_at(self, address: str, slot: str) -> str:
        return await self.request("eth_getStorageAt", [address, slot, "latest"])

    async def eth_call(self, to: str, data: str, overrides: dict | None = None, sender: str | None = None) -> str:
        tx = {"to": to, "data": data}
        if sender:
            tx["from"] = sender
        params = [tx, "latest"]
        if overrides:
            params.append(overrides)
        return await self.request("eth_call", params)

    async def call_fn(self, to: str, signature: str, out_types: list[str], arg_types=(), args=()):
        """Call a view function by its signature, e.g. call_fn(t, "decimals()", ["uint8"])."""
        data = "0x" + (function_signature_to_4byte_selector(signature) + encode(list(arg_types), list(args))).hex()
        raw = await self.eth_call(to, data)
        raw_bytes = bytes.fromhex(raw[2:])
        if not raw_bytes and out_types:
            raise RpcError(f"{signature}: empty return data")
        return decode(out_types, raw_bytes)

    async def try_call_fn(self, to: str, signature: str, out_types: list[str], arg_types=(), args=()):
        """Like call_fn but returns None if the function is missing or reverts."""
        try:
            return await self.call_fn(to, signature, out_types, arg_types, args)
        except (RpcError, ValueError, TypeError, OverflowError) as exc:
            log.debug("%s on %s failed: %s", signature, to, exc)
            return None
        except Exception as exc:  # eth_abi decoding errors
            if exc.__class__.__module__.startswith("eth_abi"):
                return None
            raise
