from conftest import EvmRpc
from evm import artifact
from rhscanner.checks.contract import check_contract, find_risky_functions


def test_risky_function_detection():
    assert set(find_risky_functions(artifact("TaxToken")["deployedBytecode"])) == {"mint", "blacklist"}
    assert find_risky_functions(artifact("MockWETH")["deployedBytecode"]) == {}


async def test_owned_token_with_mint_is_flagged(market_factory):
    chain, addrs = market_factory()
    data, findings = await check_contract(EvmRpc(chain), None, addrs["token"])
    codes = {f.code for f in findings}
    assert data["renounced"] is False
    assert {"owned", "fn_mint", "fn_blacklist"} <= codes


async def test_renounced_token_admin_functions_are_inactive(market_factory):
    chain, addrs = market_factory(renounce=True)
    data, findings = await check_contract(EvmRpc(chain), None, addrs["token"])
    codes = {f.code for f in findings}
    assert data["renounced"] is True
    assert {"renounced", "fn_mint_inactive", "fn_blacklist_inactive"} <= codes
    assert "fn_mint" not in codes


async def test_address_without_code_is_critical(market_factory):
    chain, _ = market_factory()
    _, findings = await check_contract(EvmRpc(chain), None, "0x" + "5" * 40)
    assert findings[0].severity == "critical"
