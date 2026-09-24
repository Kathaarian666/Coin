from rhscanner.checks.holders import TRANSFER_TOPIC, analyse_holders, collect_holders

SUPPLY = 1_000_000
POOL = "0xpool"
DEV = "0xdev"


def holder(addr, value):
    return {"address": {"hash": addr}, "value": str(value)}


def test_concentration_and_creator_share():
    holders = [holder(POOL, 500_000), holder("0x000000000000000000000000000000000000dead", 100_000),
               holder(DEV, 150_000)] + [holder(f"0x{i}", 25_000) for i in range(10)]
    data, findings = analyse_holders(holders, SUPPLY, {POOL}, DEV)
    assert data["creator_pct"] == 15.0
    assert data["burned_pct"] == 10.0
    assert data["top10_pct"] == 37.5  # dev 15% + nine wallets at 2.5%; pool and burn excluded
    codes = {f.code for f in findings}
    assert {"top10_mid", "creator_high", "burned"} <= codes


def test_well_distributed_supply():
    holders = [holder(f"0x{i}", 10_000) for i in range(20)]
    data, findings = analyse_holders(holders, SUPPLY, set(), None)
    assert data["top10_pct"] == 10.0
    assert [f.code for f in findings] == ["top10_ok"]


class TransferRpc:
    """Serves Transfer logs, failing wide ranges the way the public node does."""

    def __init__(self, transfers, balances, contracts=()):
        self.transfers, self.balances, self.contracts = transfers, balances, set(contracts)

    async def block_number(self):
        return 5_000_000

    async def get_logs(self, lo, hi, topics, address=None, retries=4):
        if hi - lo > 1_500_000:
            raise RuntimeError("logs matched by query exceeds limit of 10000")
        return [
            {"topics": [TRANSFER_TOPIC, "0x" + frm[2:].rjust(64, "0"), "0x" + to[2:].rjust(64, "0")],
             "data": hex(amount)}
            for block, frm, to, amount in self.transfers if lo <= block <= hi
        ]

    async def try_call_fn(self, to, signature, out, arg_types=(), args=()):
        return (self.balances.get(args[0], 0),)

    async def get_code(self, addr):
        return "0x6080" if addr in self.contracts else "0x"


async def test_collect_holders_from_transfer_logs():
    zero = "0x" + "0" * 40
    curve, alice, bob = "0x" + "c" * 40, "0x" + "a" * 40, "0x" + "b" * 40
    rpc = TransferRpc(
        transfers=[(4_900_000, zero, curve, 1000), (4_950_000, curve, alice, 300), (4_990_000, curve, bob, 100)],
        balances={curve: 600, alice: 250, bob: 100},  # alice sold some since
        contracts={curve},
    )
    items = await collect_holders(rpc, "0xtoken", lookback_blocks=10_000_000)
    by_addr = {i["address"]["hash"]: i for i in items}
    assert by_addr[alice]["value"] == "250" and not by_addr[alice]["address"]["is_contract"]
    assert by_addr[curve]["address"]["is_contract"] is True
    data, _ = analyse_holders(items, 1000, set(), None)
    assert data["contracts_pct"] == 60.0 and data["top10_pct"] == 35.0
