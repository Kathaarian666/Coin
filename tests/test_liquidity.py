from rhscanner.checks.liquidity import check_liquidity

PONS_HOOK = "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544"


class HookRpc:
    def __init__(self, hooks):
        self.hooks = hooks

    async def block_number(self):
        return 1000

    async def get_logs(self, lo, hi, topics, address=None, retries=4):
        words = ["0" * 64, "0" * 64, self.hooks[2:].rjust(64, "0"), "0" * 64, "0" * 64]
        return [{"data": "0x" + "".join(words)}]


def v4_pool():
    return {"dex": "v4", "pool": "0x" + "ab" * 32, "token": "0x" + "1" * 40, "quote": "0x" + "0" * 40}


async def test_known_launchpad_hook_is_not_penalised():
    data, findings = await check_liquidity(HookRpc(PONS_HOOK), None, v4_pool(), "0x" + "e" * 40, "0xpm")
    assert data["launchpad"].startswith("Pons")
    assert {f.code: f.severity for f in findings}["v4_known_hook"] == "info"


async def test_unknown_hook_is_flagged():
    _, findings = await check_liquidity(HookRpc("0x" + "9" * 40), None, v4_pool(), "0x" + "e" * 40, "0xpm")
    assert {f.code: f.severity for f in findings}["v4_hooks"] == "medium"
