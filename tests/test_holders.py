from rhscanner.checks.holders import analyse_holders

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
