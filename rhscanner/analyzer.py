"""Runs every check for a token and assembles a report."""

import logging
import time

from eth_utils import is_address, to_checksum_address

from .checks import Finding
from .checks.contract import check_contract
from .checks.holders import check_holders, scan_transfers
from .checks.launch import analyse_launch, launch_logs
from .checks.honeypot import check_honeypot
from .checks.liquidity import check_liquidity
from .fomo import FOMO_ENTRY, FOMO_EXECUTOR
from .rpc import RpcClient
from .scoring import missing_checks, score
from .sources import Blockscout, DexScreener

log = logging.getLogger(__name__)


def pool_from_dexscreener(token: str, pairs: list[dict]) -> dict | None:
    """Pick the deepest pool of `token`, whatever it is paired with.

    On Robinhood Chain the main pool is often against a stock token (e.g. DJT)
    rather than ETH or USDG, so the counter asset cannot be assumed.
    """
    candidates = []
    for p in pairs:
        base = (p.get("baseToken") or {}).get("address", "").lower()
        quote = (p.get("quoteToken") or {}).get("address", "").lower()
        if quote == token.lower():
            base, quote = quote, base
        if base != token.lower():
            continue
        labels = [label.lower() for label in p.get("labels") or []]
        address = p.get("pairAddress", "")
        dex = "v4" if "v4" in labels or len(address) == 66 else "v3" if "v3" in labels else "v2"
        liquidity = (p.get("liquidity") or {}).get("usd") or 0
        candidates.append((liquidity, {
            "dex": dex, "pool": address, "token": token, "quote": quote, "hooks": None,
            "quote_symbol": (p.get("quoteToken") or {}).get("symbol") if base == token.lower() else None,
        }))
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
        "change_m5": (pair.get("priceChange") or {}).get("m5"),
        # all of the token's pools, so Fomo's share of volume is not overstated
        "volume_h1_all": sum((p.get("volume") or {}).get("h1") or 0 for p in pairs),
        "pair_created_at": pair.get("pairCreatedAt"),
        "url": pair.get("url"),
        "socials": [s.get("type") for s in (pair.get("info") or {}).get("socials") or []],
        "websites": len((pair.get("info") or {}).get("websites") or []),
    }


def market_findings(market: dict, have_eth_liquidity: bool) -> list[Finding]:
    findings = []
    liquidity = market.get("liquidity_usd")
    if liquidity is not None and not have_eth_liquidity:
        if liquidity < 1000:
            findings.append(Finding("high", "liq_usd_low", f"Likidite çok düşük: ${liquidity:,.0f}"))
        elif liquidity < 5000:
            findings.append(Finding("medium", "liq_usd_mid", f"Likidite düşük: ${liquidity:,.0f}"))
    buys, sells = market.get("buys_h1") or 0, market.get("sells_h1") or 0
    if sells > 2 * max(buys, 1) and sells >= 10:
        findings.append(Finding("low", "sell_pressure", f"Son 1 saatte satış baskısı: {buys} alım / {sells} satış"))
    if market and not market.get("socials") and not market.get("websites"):
        findings.append(Finding("low", "no_socials", "Sosyal medya / web sitesi bilgisi yok"))
    return findings


def fomo_findings(fomo: dict) -> list[Finding]:
    findings = []
    if fomo.get("sellers", 0) >= 2:
        findings.append(Finding(
            "good", "fomo_sellable", f"Fomo'da {fomo['sellers']} farklı kullanıcı satış yapabildi (satılabiliyor)"
        ))
    elif fomo.get("buyers", 0) >= 5 and not fomo.get("sells"):
        findings.append(Finding("low", "fomo_no_sells", "Fomo'da çok alım var ama henüz hiç satış yok"))
    buy_usd, sell_usd = fomo.get("buy_usd") or 0, fomo.get("sell_usd") or 0
    if sell_usd >= 1000 and sell_usd > 2 * buy_usd:
        findings.append(Finding(
            "medium", "fomo_dumping", f"Fomo'da satış baskısı: ${sell_usd:,.0f} satış / ${buy_usd:,.0f} alım"
        ))
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
        return pool_from_dexscreener(token, pairs), pairs

    async def analyze(self, token: str, pool: dict | None = None, fomo: dict | None = None) -> dict:
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
            "fomo": fomo,
        }
        if any(f.code == "no_code" for f in findings):
            return self._finish(report, findings)

        # The V4 PoolManager holds every V4 pool's liquidity; Fomo's contracts only pass tokens through.
        exclude = {token, self.settings.v4_pool_manager, FOMO_ENTRY, FOMO_EXECUTOR}
        if pool:
            exclude.add(pool["pool"])
            if pool.get("factory") and pool["dex"] == "v4":
                exclude.add(pool["factory"])
            liq_data, liq_findings = await check_liquidity(
                self.rpc, self.blockscout, pool, self.settings.weth,
                self.settings.v4_pool_manager, self.settings.holder_lookback_blocks,
            )
            hp_data, hp_findings = await check_honeypot(self.rpc, pool, self.settings.weth, self.settings.probe_eth)
            report.update(liquidity=liq_data, honeypot=hp_data)
            findings += liq_findings + hp_findings
        else:
            findings.append(Finding("medium", "no_pool", "WETH/ETH havuzu bulunamadı — likidite ve honeypot kontrol edilemedi"))

        try:
            transfer_logs = await scan_transfers(self.rpc, token, self.settings.holder_lookback_blocks)
        except Exception as exc:
            log.warning("transfer scan for %s failed: %s", token, exc)
            transfer_logs = []
        try:
            launch = await launch_logs(self.rpc, token, self.settings.holder_lookback_blocks)
            launch_data, launch_findings = await analyse_launch(self.rpc, token, launch, meta["total_supply"], exclude)
        except Exception as exc:
            log.warning("launch analysis for %s failed: %s", token, exc)
            launch_data, launch_findings = {}, []
        report["launch"] = launch_data
        findings += launch_findings

        holder_data, holder_findings = await check_holders(
            self.rpc, token, meta["total_supply"], exclude,
            contract_data.get("creator") or launch_data.get("creator"),
            self.settings.holder_lookback_blocks, logs=transfer_logs or None,
        )
        report["holders"] = holder_data
        findings += holder_findings

        market = market_summary(pairs, pool["pool"] if pool else None)
        report["market"] = market
        findings += market_findings(market, "liquidity_eth" in (report.get("liquidity") or {}))

        if fomo:
            findings += fomo_findings(fomo)
            if any(f.code == "fomo_sellable" for f in findings):
                # Real users selling successfully is stronger evidence than our simulation.
                findings = [
                    Finding("info", f.code, f.message) if f.code in ("not_simulated", "sim_error") else f
                    for f in findings
                ]
        return self._finish(report, findings)

    @staticmethod
    def _finish(report: dict, findings: list[Finding]) -> dict:
        report["score"] = score(findings)
        report["missing"] = missing_checks(findings)
        report["findings"] = [f.to_dict() for f in findings]
        return report

