"""Honeypot / tax detection by simulating a buy and a sell with eth_call.

The HoneypotProbe contract (contracts/HoneypotProbe.sol) is injected at a
throwaway address via a state override, so nothing is deployed or spent.
Only Uniswap V2 style pairs quoted in WETH can be simulated for now.
"""

import json
from functools import lru_cache
from pathlib import Path

from eth_abi import decode, encode
from eth_utils import function_signature_to_4byte_selector

from ..rpc import RpcClient, RpcError
from . import Finding

PROBE_ARTIFACT = Path(__file__).resolve().parents[2] / "contracts" / "build" / "HoneypotProbe.json"
PROBE_ADDRESS = "0x00000000000000000000000000000000c0ffee01"
PROBE_CALLER = "0x00000000000000000000000000000000c0ffee02"
PROBE_SIGNATURE = "probe(address,address,address,uint256,uint256)"
RESULT_TYPES = ["(uint256,uint256,uint256,uint256,uint256,uint8)"]
# Assume up to 1% swap fee so forks with fees above Uniswap's 0.3% still pass the K check.
FEE_BPS = 100


@lru_cache(maxsize=1)
def probe_runtime_code() -> str:
    return json.loads(PROBE_ARTIFACT.read_text())["deployedBytecode"]


def probe_calldata(pair: str, token: str, weth: str, amount_in: int) -> str:
    selector = function_signature_to_4byte_selector(PROBE_SIGNATURE)
    args = encode(
        ["address", "address", "address", "uint256", "uint256"], [pair, token, weth, amount_in, FEE_BPS]
    )
    return "0x" + (selector + args).hex()


def _tax_pct(sent: int, received: int) -> float:
    return 0.0 if not sent else max(0.0, 100.0 * (sent - received) / sent)


def _tax_finding(kind: str, pct: float) -> Finding | None:
    label = "Alım" if kind == "buy" else "Satış"
    if pct >= 50:
        return Finding("critical", f"{kind}_tax_extreme", f"{label} vergisi %{pct:.1f} — fiilen satılamaz")
    if pct >= 20:
        return Finding("high", f"{kind}_tax_high", f"{label} vergisi yüksek: %{pct:.1f}")
    if pct >= 10:
        return Finding("medium", f"{kind}_tax_mid", f"{label} vergisi: %{pct:.1f}")
    if pct >= 1:
        return Finding("low", f"{kind}_tax_low", f"{label} vergisi: %{pct:.1f}")
    return None


def interpret(result: tuple) -> tuple[dict, list[Finding]]:
    buy_requested, buy_received, sell_sent, sell_arrived, weth_out, failed_stage = result
    data = {"simulated": True, "failed_stage": failed_stage}
    if failed_stage == 1:
        return data, [Finding(
            "high", "buy_failed",
            "Alım simülasyonu başarısız — trading kapalı olabilir veya anti-bot koruması var",
        )]
    if failed_stage in (2, 3):
        return data, [Finding("critical", "honeypot", "HONEYPOT: alınabiliyor ama SATILAMIYOR")]

    buy_tax = _tax_pct(buy_requested, buy_received)
    sell_tax = _tax_pct(sell_sent, sell_arrived)
    data.update(buy_tax=round(buy_tax, 2), sell_tax=round(sell_tax, 2), weth_out=weth_out)
    findings = [f for f in (_tax_finding("buy", buy_tax), _tax_finding("sell", sell_tax)) if f]
    if not findings:
        findings.append(Finding("good", "sellable", "Alım-satım simülasyonu başarılı, vergi yok"))
    else:
        findings.append(Finding("good", "sellable_taxed", "Satış mümkün (simülasyon başarılı)"))
    return data, findings


async def check_honeypot(rpc: RpcClient, pool: dict, weth: str, probe_eth: float) -> tuple[dict, list[Finding]]:
    if pool["dex"] != "v2" or pool["quote"].lower() != weth.lower():
        return {"simulated": False}, [Finding(
            "medium", "not_simulated", f"Honeypot simülasyonu yapılamadı ({pool['dex'].upper()} havuzu)"
        )]

    reserve = await rpc.try_call_fn(weth, "balanceOf(address)", ["uint256"], ["address"], [pool["pool"]])
    weth_reserve = reserve[0] if reserve else 0
    if not weth_reserve:
        return {"simulated": False}, [Finding("high", "no_liquidity", "Havuzda likidite yok, simülasyon yapılamadı")]

    amount_in = min(int(probe_eth * 1e18), weth_reserve // 100)
    overrides = {
        PROBE_ADDRESS: {"code": probe_runtime_code(), "balance": hex(amount_in * 2)},
        PROBE_CALLER: {"balance": hex(10**18)},  # gas money, in case the node checks it
    }
    data = probe_calldata(pool["pool"], pool["token"], weth, amount_in)
    try:
        raw = await rpc.eth_call(PROBE_ADDRESS, data, overrides=overrides, sender=PROBE_CALLER)
        result = decode(RESULT_TYPES, bytes.fromhex(raw[2:]))[0]
    except (RpcError, ValueError) as exc:
        return {"simulated": False, "error": str(exc)[:200]}, [Finding(
            "medium", "sim_error", "Honeypot simülasyonu çalıştırılamadı"
        )]
    return interpret(result)
