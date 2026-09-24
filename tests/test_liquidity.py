from rhscanner.checks.liquidity import check_liquidity
from rhscanner.hooks import HookRegistry

PONS_HOOK = "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544"
COMMON_HOOK = "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044"


def init_log(hook):
    words = ["0" * 64, "0" * 64, hook[2:].rjust(64, "0"), "0" * 64, "0" * 64]
    return {"data": "0x" + "".join(words)}


class HookRpc:
    def __init__(self, hooks, upgradeable=False, init_logs=None):
        self.hooks, self.upgradeable, self.init_logs = hooks, upgradeable, init_logs

    async def block_number(self):
        return 1000

    async def get_logs(self, lo, hi, topics, address=None, retries=4):
        if self.init_logs is not None:
            return self.init_logs if lo == 0 else []
        return [init_log(self.hooks)]

    async def get_storage_at(self, address, slot):
        return "0x" + ("1" if self.upgradeable else "0").rjust(64, "0")


def v4_pool():
    return {"dex": "v4", "pool": "0x" + "ab" * 32, "token": "0x" + "1" * 40, "quote": "0x" + "0" * 40}


async def check(rpc):
    data, findings = await check_liquidity(rpc, None, v4_pool(), "0x" + "e" * 40, "0xpm", registry=HookRegistry())
    return data, {f.code: f for f in findings}


async def test_named_launchpad_hook_is_not_penalised():
    data, findings = await check(HookRpc(PONS_HOOK))
    assert data["launchpad"].startswith("Pons") and findings["v4_known_hook"].severity == "info"


async def test_widely_used_hook_is_only_a_low_note():
    data, findings = await check(HookRpc(COMMON_HOOK))
    assert findings["v4_common_hook"].severity == "low" and "351" in findings["v4_common_hook"].message


async def test_rare_hook_is_flagged_and_worse_when_upgradeable():
    _, findings = await check(HookRpc("0x" + "9" * 40))
    assert findings["v4_hooks"].severity == "medium"
    _, findings = await check(HookRpc("0x" + "9" * 40, upgradeable=True))
    assert findings["v4_hooks"].severity == "high" and "yükseltilebilir" in findings["v4_hooks"].message


async def test_registry_refresh_counts_hooks():
    rare = "0x" + "7" * 40
    rpc = HookRpc(None, init_logs=[init_log(rare)] * 3 + [init_log("0x" + "0" * 40)])
    registry = HookRegistry(counts={})
    await registry.refresh(rpc, "0xpm")
    assert registry.pools(rare) == 3 and registry.pools("0x" + "0" * 40) == 0
