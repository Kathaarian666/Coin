import pytest

from conftest import EvmRpc
from rhscanner.checks.honeypot import check_honeypot, interpret


def pool_for(addrs):
    return {"dex": "v2", "pool": addrs["pair"], "token": addrs["token"], "quote": addrs["weth"]}


async def run(market_factory, **kwargs):
    chain, addrs = market_factory(**kwargs)
    rpc = EvmRpc(chain, addrs["probe"])
    return await check_honeypot(rpc, pool_for(addrs), addrs["weth"], probe_eth=0.01)


async def test_clean_token_is_sellable_without_tax(market_factory):
    data, findings = await run(market_factory)
    assert data["buy_tax"] == 0 and data["sell_tax"] == 0
    assert [f.code for f in findings] == ["sellable"]


async def test_taxes_are_measured(market_factory):
    data, findings = await run(market_factory, buy_tax=500, sell_tax=2500)
    assert data["buy_tax"] == pytest.approx(5.0, abs=0.01)
    assert data["sell_tax"] == pytest.approx(25.0, abs=0.01)
    codes = {f.code for f in findings}
    assert {"buy_tax_low", "sell_tax_high"} <= codes


async def test_extreme_sell_tax_is_critical(market_factory):
    _, findings = await run(market_factory, sell_tax=9000)
    assert any(f.severity == "critical" and f.code == "sell_tax_extreme" for f in findings)


async def test_blocked_sells_are_a_honeypot(market_factory):
    data, findings = await run(market_factory, block_sells=True)
    assert data["failed_stage"] == 2
    assert [f.code for f in findings] == ["honeypot"]


async def test_non_v2_pools_are_not_simulated():
    pool = {"dex": "v3", "pool": "0x" + "1" * 40, "token": "0x" + "2" * 40, "quote": "0x" + "3" * 40}
    data, findings = await check_honeypot(None, pool, "0x" + "3" * 40, 0.01)
    assert data == {"simulated": False}
    assert findings[0].code == "not_simulated"


def test_interpret_buy_failure():
    _, findings = interpret((100, 0, 0, 0, 0, 1))
    assert findings[0].code == "buy_failed"
