from rhscanner.checks.launch import analyse_launch

TOKEN = "0x" + "7" * 40
CURVE, DEV, BUNDLER, SNIPER, LATE = ("0x" + c * 40 for c in "cdbse")
ZERO = "0x" + "0" * 40
SUPPLY = 1_000_000


def transfer(frm, to, amount, block, tx):
    return {"topics": ["0xddf2", "0x" + frm[2:].rjust(64, "0"), "0x" + to[2:].rjust(64, "0")],
            "data": hex(amount), "blockNumber": hex(block), "transactionHash": tx}


class LaunchRpc:
    def __init__(self, balances):
        self.balances = balances

    async def block_timestamp(self, number):
        raise RuntimeError("not needed")

    async def request(self, method, params):
        assert method == "eth_getTransactionByHash"
        return {"from": DEV, "to": "0xfactory"}

    async def get_code(self, address):
        return "0x6080" if address == CURVE else "0x"

    async def try_call_fn(self, token, sig, out, types, args):
        return (self.balances.get(args[0], 0),)


async def test_dev_bundle_and_snipers_are_measured():
    logs = [
        transfer(ZERO, CURVE, SUPPLY, 100, "0xlaunch"),
        transfer(CURVE, DEV, 200_000, 100, "0xlaunch"),       # dev buy in the launch tx
        transfer(CURVE, BUNDLER, 150_000, 100, "0xlaunch"),   # bundled wallet in the same tx
        transfer(CURVE, SNIPER, 120_000, 105, "0xsnipe"),     # first seconds
        transfer(CURVE, LATE, 50_000, 500, "0xlate"),         # after the sniper window
    ]
    rpc = LaunchRpc({DEV: 20_000, BUNDLER: 150_000, SNIPER: 120_000})
    data, findings = await analyse_launch(rpc, TOKEN, logs, SUPPLY, exclude=set())
    assert data["creator"] == DEV and data["dev_initial_pct"] == 20.0 and data["dev_pct"] == 2.0
    assert (data["bundle_pct"], data["sniper_pct"]) == (15.0, 12.0)
    codes = {f.code for f in findings}
    assert {"dev_sold", "bundled", "snipers_mid"} <= codes


async def test_no_mint_in_logs_means_no_verdict():
    assert await analyse_launch(LaunchRpc({}), TOKEN, [], SUPPLY, set()) == ({}, [])
