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


IMPL = "ab" * 20
EIP1167 = "0x363d3d373d3d3d363d73" + IMPL + "5af43d82803e903d91602b57fd5bf3"
PUSH0_CLONE = "0x365f5f375f5f365f73" + IMPL + "5af43d5f5f3e5f3d91602a57fd5bf3"
# a 44-byte clone as found on Robinhood Chain (0x6a828e4c...), template 0x3be8b97f...
CHAIN_CLONE = "0x3d3d3d3d363d3d37363d733be8b97fd0e713b5abe0649fa830223b6b4bc5995af43d3d93803e602a57fd5bf3"


def test_minimal_proxy_target_knows_both_clone_kinds():
    from rhscanner.checks.contract import minimal_proxy_target

    assert len(bytes.fromhex(EIP1167[2:])) == 45 and len(bytes.fromhex(PUSH0_CLONE[2:])) == 44
    assert minimal_proxy_target(EIP1167) == "0x" + IMPL
    assert minimal_proxy_target(PUSH0_CLONE.upper().replace("0X", "0x")) == "0x" + IMPL
    assert minimal_proxy_target(CHAIN_CLONE) == "0x3be8b97fd0e713b5abe0649fa830223b6b4bc599"
    assert minimal_proxy_target(artifact("TaxToken")["deployedBytecode"]) is None
    assert minimal_proxy_target("0x73" + IMPL + "5af4" + "00" * 80) is None  # long code is not a clone


async def test_push0_clone_is_analysed_through_its_implementation():
    token_code = artifact("TaxToken")["deployedBytecode"]

    class Rpc:
        async def get_code(self, addr):
            return PUSH0_CLONE if addr == "0xtoken" else token_code

        async def get_storage_at(self, addr, slot):
            return "0x" + "0" * 64

        async def try_call_fn(self, *args, **kwargs):
            return None

    data, findings = await check_contract(Rpc(), None, "0xtoken")
    codes = {f.code for f in findings}
    assert data["clone_of"] == "0x" + IMPL
    assert "clone" in codes and "fn_mint_inactive" in codes  # the template's functions are seen
