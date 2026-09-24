"""Runs every check for a token and assembles a report."""

import logging
import time

from eth_utils import is_address, to_checksum_address

from .checks import Finding
from .checks.contract import check_contract
from .checks.holders import check_holders
from .checks.honeypot import check_honeypot
from .checks.liquidity import check_liquidity
from .rpc import RpcClient
from .scoring import score
from .sources import Blockscout, DexScreener

log = logging.getLogger(__name__)


def pool_from_dexscreener(token: str, pairs: list[dict], quote_tokens: set[str]) -> dict | None:
    """Pick the deepest pair of `token` against WETH/ETH (or a configured quote)."""
    candidates = []
    for p in pairs:
        base = (p.get("baseToken") or {}).get("address", "").lower()
        quote = (p.get("quoteToken") or {}).get("address", "").lower()
        if base == token.lower() and quote in quote_tokens:
            pass
        elif quote == token.lower() and base in quote_tokens:
            base, quote = quote, base
        else:
            continue
        labels = [label.lower() for label in p.get("labels") or []]
        address = p.get("pairAddress", "")
        dex = "v4" if "v4" in labels or len(address) == 66 else "v3" if "v3" in labels else "v2"
        liquidity = (p.get("liquidity") or {}).get("usd") or 0
        candidates.append((liquidity, {"dex": dex, "pool": address, "token": token, "quote": quote, "hooks": None}))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def market_summary(pairs: list[dict], pool_address: str | None) -> dict:
    pair = next((p for p in pairs if (p.get("pairAddress") or "").lower() == (pool_address or "").lower()), None)
    pair = pair or (pairs[0] if pairs else None)
    if not pair:
        return {}
    h1 = (pair.get("txns") or {}).get("h1") or {}
    return {
        "price_usd": pair.get("priceUsd"),
        "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
        "fdv": pair.get("fdv"),
        "volume_h1": (pair.get("volume") or {}).get("h1"),
        "buys_h1": h1.get("buys"),
        "sells_h1": h1.get("sells"),
        "change_h1": (pair.get("priceChange") or {}).get("h1"),
        "url": pair.get("url"),
        "socials": [s.get("type") for s in (pair.get("info") or {}).get("socials") or []],
        "websites": len((pair.get("info") or {}).get("websites") or []),
    }


def market_findings(market: dict) -> list[Finding]:
    findings = []
    buys, sells = market.get("buys_h1") or 0, market.get("sells_h1") or 0
    if sells > 2 * max(buys, 1) and sells >= 10:
        findings.append(Finding("low", "sell_pressure", f"Son 1 saatte satış baskısı: {buys} alım / {sells} satış"))
    if market and not market.get("socials") and not market.get("websites"):
        findings.append(Finding("low", "no_socials", "Sosyal medya / web sitesi bilgisi yok"))
    return findings


class Analyzer:
    def __init__(self, rpc: RpcClient, settings, blockscout: Blockscout | None, dexscreener: DexScreener | None, storage):
        self.rpc = rpc
        self.settings = settings
        self.blockscout = blockscout
        self.dexscreener = dexscreener
        self.storage = storage

    async def _metadata(self, token: str) -> dict:
        name = await self.rpc.try_call_fn(token, "name()", ["string"])
        symbol = await self.rpc.try_call_fn(token, "symbol()", ["string"])
        decimals = await self.rpc.try_call_fn(token, "decimals()", ["uint8"])
        supply = await self.rpc.try_call_fn(token, "totalSupply()", ["uint256"])
        return {
            "name": name[0] if name else "?",
            "symbol": symbol[0] if symbol else "?",
            "decimals": decimals[0] if decimals else 18,
            "total_supply": supply[0] if supply else 0,
        }

    async def resolve_pool(self, token: str) -> tuple[dict | None, list[dict]]:
        pairs = await self.dexscreener.token_pairs(token) if self.dexscreener else []
        known = self.storage.known_pool(token)
        if known:
            return known, pairs
        return pool_from_dexscreener(token, pairs, self.settings.quote_tokens), pairs

    async def analyze(self, token: str, pool: dict | None = None) -> dict:
        if not is_address(token):
            raise ValueError("Geçersiz adres")
        token = to_checksum_address(token)
        pairs: list[dict] = []
        if pool is None:
            pool, pairs = await self.resolve_pool(token)
        elif self.dexscreener:
            pairs = await self.dexscreener.token_pairs(token)

        meta = await self._metadata(token)
        contract_data, findings = await check_contract(self.rpc, self.blockscout, token)
        report = {
            "token": token,
            **meta,
            "pool": pool,
            "checked_at": time.time(),
            "contract": contract_data,
        }
        if any(f.code == "no_code" for f in findings):
            return self._finish(report, findings)

        exclude = {token}
        if pool:
            exclude.add(pool["pool"])
            if pool.get("factory") and pool["dex"] == "v4":
                exclude.add(pool["factory"])  # the PoolManager holds all V4 liquidity
            liq_data, liq_findings = await check_liquidity(self.rpc, self.blockscout, pool, self.settings.weth)
            hp_data, hp_findings = await check_honeypot(self.rpc, pool, self.settings.weth, self.settings.probe_eth)
            report.update(liquidity=liq_data, honeypot=hp_data)
            findings += liq_findings + hp_findings
        else:
            findings.append(Finding("medium", "no_pool", "WETH/ETH havuzu bulunamadı — likidite ve honeypot kontrol edilemedi"))

        holder_data, holder_findings = await check_holders(
            self.blockscout, token, meta["total_supply"], exclude, contract_data.get("creator")
        )
        report["holders"] = holder_data
        findings += holder_findings

        market = market_summary(pairs, pool["pool"] if pool else None)
        report["market"] = market
        findings += market_findings(market)
        return self._finish(report, findings)

    @staticmethod
    def _finish(report: dict, findings: list[Finding]) -> dict:
        report["score"] = score(findings)
        report["findings"] = [f.to_dict() for f in findings]
        return report

