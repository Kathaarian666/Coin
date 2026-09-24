"""Free HTTP data sources: Blockscout (explorer) and DexScreener (market data)."""

import logging

import httpx

from .config import DEXSCREENER_CHAIN

log = logging.getLogger(__name__)


class Blockscout:
    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self.base = base_url.rstrip("/")
        self.http = client

    async def _get(self, path: str, params: dict | None = None) -> dict | None:
        try:
            resp = await self.http.get(f"{self.base}/api/v2{path}", params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("blockscout %s failed: %s", path, exc)
            return None

    async def address_info(self, address: str) -> dict | None:
        return await self._get(f"/addresses/{address}")

    async def smart_contract(self, address: str) -> dict | None:
        return await self._get(f"/smart-contracts/{address}")

    async def token_holders(self, address: str) -> list[dict] | None:
        data = await self._get(f"/tokens/{address}/holders")
        return None if data is None else data.get("items", [])

    async def token_info(self, address: str) -> dict | None:
        return await self._get(f"/tokens/{address}")


class DexScreener:
    BASE = "https://api.dexscreener.com"

    def __init__(self, client: httpx.AsyncClient):
        self.http = client

    async def token_pairs(self, token: str) -> list[dict]:
        try:
            resp = await self.http.get(f"{self.BASE}/token-pairs/v1/{DEXSCREENER_CHAIN}/{token}")
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("dexscreener lookup for %s failed: %s", token, exc)
            return []
        return data if isinstance(data, list) else data.get("pairs") or []
