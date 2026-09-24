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


def _retry_after(resp: httpx.Response, default: float) -> float:
    try:
        return min(10.0, max(0.5, float(resp.headers.get("retry-after", default))))
    except ValueError:
        return default


class RetryableHttpError(Exception):
    """A response worth retrying elsewhere: rate limited, blocked or server error."""


class RateLimited(RetryableHttpError):
    def __init__(self, wait: float):
        super().__init__("HTTP 429")
        self.wait = wait


class RpcClient:
    """JSON-RPC client over a primary endpoint plus optional fallbacks.

    General calls go to the active endpoint: a rate limit is waited out a
    couple of times, then (or on 403/5xx/network errors) the client moves to
    the next endpoint and returns to the primary after PRIMARY_RETRY_SECONDS.

    eth_getLogs is routed by range. Robinhood's public RPC rate-limits log
    queries hard (429s even at 1 req/s) while dRPC's keyless tier serves only
    short ranges, so short ranges (the Fomo poller's) go to the first fallback
    and long ones (holder and hook scans) to the primary, patiently.
    """

    PRIMARY_RETRY_SECONDS = 60
    RATE_LIMIT_WAITS = 2
    LOG_RATE_LIMIT_WAITS = 6
    SMALL_LOG_RANGE = 90

    def __init__(self, url: str, max_rps: float = 8.0, client: httpx.AsyncClient | None = None,
                 fallback_urls: list[str] | tuple = ()):
        self.urls = [url, *[u for u in fallback_urls if u and u != url]]
        self.active = 0
        self._switched_at = 0.0
        self.http = client or httpx.AsyncClient(timeout=20)
        self.limiter = RateLimiter(max_rps)
        self._ids = itertools.count(1)

    @property
    def url(self) -> str:
        return self.urls[self.active]

    async def close(self):
        await self.http.aclose()

    def _fail_over(self, reason: str):
        if len(self.urls) < 2:
            return False
        previous = self.url
        self.active = (self.active + 1) % len(self.urls)
        self._switched_at = time.monotonic()
        log.warning("RPC %s failed (%s); switching to %s", previous, reason, self.url)
        return True

    async def _send(self, url: str, method: str, payload: dict, backoff: float):
        await self.limiter.wait()
        resp = await self.http.post(url, json=payload)
        if resp.status_code == 429:
            raise RateLimited(_retry_after(resp, default=backoff))
        if resp.status_code == 403 or resp.status_code >= 500:
            raise RetryableHttpError(f"HTTP {resp.status_code}")
        if resp.status_code == 400:
            # Some providers (dRPC) answer JSON-RPC errors such as range limits with 400.
            try:
                error = resp.json().get("error")
            except ValueError:
                error = None
            if error:
                raise RpcError(f"{method}: {error}")
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RpcError(f"{method}: {body['error']}")
        return body["result"]

    async def request(self, method: str, params: list, retries: int = 4,
                      endpoint: int | None = None, rate_limit_waits: int | None = None):
        """endpoint pins the call to one URL (no fail-over); otherwise the active one is used."""
        if endpoint is None and self.active and time.monotonic() - self._switched_at > self.PRIMARY_RETRY_SECONDS:
            self.active = 0  # give the primary endpoint another chance
        waits_left = self.RATE_LIMIT_WAITS if rate_limit_waits is None else rate_limit_waits
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        delay = 1.0
        failures = 0
        while True:
            url = self.urls[endpoint] if endpoint is not None else self.url
            try:
                return await self._send(url, method, payload, delay)
            except RateLimited as exc:
                if waits_left > 0:
                    waits_left -= 1
                    log.info("RPC %s rate limited, waiting %.1fs", url, exc.wait)
                    await asyncio.sleep(exc.wait)
                    delay = min(delay * 2, 8.0)
                    continue
                reason = str(exc)
            except (httpx.TransportError, httpx.HTTPStatusError, RetryableHttpError, ValueError) as exc:
                reason = str(exc) or exc.__class__.__name__
            failures += 1
            if failures > retries:
                if endpoint is None:
                    self._fail_over(reason)  # so the next call starts on a healthier endpoint
                raise RetryableHttpError(f"{method} via {url}: {reason}")
            if endpoint is not None or not self._fail_over(reason):
                log.warning("RPC %s failed (%s), retrying in %.0fs", method, reason, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8.0)

    async def block_number(self) -> int:
        return int(await self.request("eth_blockNumber", []), 16)

    async def get_logs(self, from_block: int, to_block: int, topics: list, address=None, retries: int = 4) -> list[dict]:
        query = {"fromBlock": hex(from_block), "toBlock": hex(to_block), "topics": topics}
        if address:
            query["address"] = address
        if len(self.urls) > 1 and to_block - from_block <= self.SMALL_LOG_RANGE:
            try:
                return await self.request("eth_getLogs", [query], retries=0, endpoint=1, rate_limit_waits=1)
            except (RpcError, RetryableHttpError) as exc:
                log.debug("short log query on %s failed (%s); using primary", self.urls[1], exc)
        return await self.request(
            "eth_getLogs", [query], retries=retries, endpoint=0, rate_limit_waits=self.LOG_RATE_LIMIT_WAITS
        )

    async def block_timestamp(self, number: int) -> int:
        block = await self.request("eth_getBlockByNumber", [hex(number), False])
        return int(block["timestamp"], 16)

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
