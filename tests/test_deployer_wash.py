from rhscanner.checks.deployer import (
    DAY_BLOCKS,
    LOOKBACK_BLOCKS,
    PONS_V2_LAUNCH,
    WINDOW_BLOCKS,
    check_deployer,
)
from rhscanner.checks.wash import TRANSFER_TOPIC, fomo_churn, recent_flow, wash_findings
from rhscanner.fomo import FomoTrade, FomoTracker
from rhscanner.momentum import momentum_score

HEAD = 50_000_000
LAUNCHER = "0x" + "1" * 40
TOKEN = "0x" + "a" * 40


def topic(address):
    return "0x" + address[2:].rjust(64, "0")


def launch_event(token, block, launcher=LAUNCHER):
    return {"topics": [PONS_V2_LAUNCH, topic(token), topic("0x" + "c" * 40), topic(launcher)],
            "blockNumber": hex(block)}


class HistoryRpc:
    def __init__(self, events, fail_windows=0):
        self.events = events
        self.fail_windows = fail_windows
        self.calls = []

    async def block_number(self):
        return HEAD

    async def get_logs(self, lo, hi, topics, address=None, retries=4):
        self.calls.append((lo, hi))
        if topics[1] is not None:  # launcher lookup by token
            return [e for e in self.events if e["topics"][1] == topics[1] and lo <= int(e["blockNumber"], 16) <= hi]
        if self.fail_windows:
            self.fail_windows -= 1
            raise TimeoutError
        return [e for e in self.events
                if e["topics"][3] == topics[3] and lo <= int(e["blockNumber"], 16) <= hi]


class FakeDex:
    def __init__(self, pairs):
        self.pairs = pairs

    async def tokens(self, addresses):
        return [p for p in self.pairs if p["baseToken"]["address"] in addresses]


def pair(token, liq, fdv):
    return {"baseToken": {"address": token}, "liquidity": {"usd": liq}, "fdv": fdv}


async def test_serial_launcher_with_dead_coins():
    old = [f"0x{i:040x}" for i in range(12)]
    events = [launch_event(TOKEN, HEAD - 100)] + [launch_event(t, HEAD - 1000 - i * 200_000) for i, t in enumerate(old)]
    dex = FakeDex([pair(t, 500, 20_000) for t in old[:11]] + [pair(old[11], 9_000, 2_000_000)])
    data, findings = await check_deployer(HistoryRpc(events), dex, TOKEN, HEAD - 100)
    codes = {f.code for f in findings}
    assert data["launcher"] == LAUNCHER
    assert data["previous_launches"] == 12
    assert data["launches_24h"] == sum(1 for i in range(12) if HEAD - 1000 - i * 200_000 >= HEAD - DAY_BLOCKS)
    assert (data["checked"], data["alive"], data["best_previous_fdv"]) == (12, 1, 2_000_000)
    assert {"serial_launcher", "launcher_dead_coins", "launcher_hit"} <= codes


async def test_history_is_queried_in_windows():
    rpc = HistoryRpc([launch_event(TOKEN, HEAD - 5)])
    data, findings = await check_deployer(rpc, None, TOKEN, HEAD - 5)
    history = [c for c in rpc.calls if c[0] != c[1]]
    assert len(history) == LOOKBACK_BLOCKS // WINDOW_BLOCKS
    assert all(hi - lo < WINDOW_BLOCKS for lo, hi in history)
    assert data["previous_launches"] == 0
    assert [f.code for f in findings] == ["first_launch"]


async def test_failed_window_does_not_claim_first_launch():
    rpc = HistoryRpc([launch_event(TOKEN, HEAD - 5)], fail_windows=3)  # a 4M window and the halves it is split into
    data, findings = await check_deployer(rpc, None, TOKEN, HEAD - 5)
    assert data["partial"] and findings == []


async def test_not_a_pons_launch_gives_no_verdict():
    data, findings = await check_deployer(HistoryRpc([]), None, TOKEN, HEAD - 5)
    assert (data, findings) == ({}, [])
    assert await check_deployer(HistoryRpc([]), None, TOKEN, None) == ({}, [])


POOL = "0x" + "b" * 40


class FlowRpc:
    def __init__(self, logs):
        self.logs = logs

    async def block_number(self):
        return HEAD

    async def get_logs(self, lo, hi, topics, address=None, retries=4):
        return self.logs

    async def get_code(self, address):
        return "0x6080" if address == POOL else "0x"


def transfer(frm, to):
    return {"topics": [TRANSFER_TOPIC, topic(frm), topic(to)]}


async def test_few_wallets_churning_is_flagged():
    wallets = [f"0x{i + 1:040x}" for i in range(4)]
    logs = [transfer(POOL, wallets[i % 4]) for i in range(30)] + [transfer(wallets[i % 4], POOL) for i in range(30)]
    flow = await recent_flow(FlowRpc(logs), TOKEN, set())
    assert flow["transfers_5m"] == 60
    assert flow["wallets_5m"] == 4  # the pool contract is left out
    assert [f.code for f in wash_findings(flow, None)] == ["wash_few_wallets"]


async def test_organic_flow_is_not_flagged():
    logs = [transfer(POOL, f"0x{i + 1:040x}") for i in range(60)]
    flow = await recent_flow(FlowRpc(logs), TOKEN, set())
    assert flow["wallets_5m"] == 60
    assert wash_findings(flow, None) == []


def test_fomo_churn_share():
    now = 10_000.0
    tracker = FomoTracker()
    for side in ("buy", "sell", "buy", "sell"):
        tracker.add(FomoTrade("0x", 1, TOKEN, side, "bot", 100, now - 60, 1))
    tracker.add(FomoTrade("0x", 1, TOKEN, "buy", "real", 100, now - 60, 1))
    tracker.add(FomoTrade("0x", 1, TOKEN, "buy", "old", 1000, now - 4000, 1))  # outside the window
    assert fomo_churn(tracker, TOKEN, now=now) == 0.8
    assert fomo_churn(tracker, "0x" + "f" * 40, now=now) is None
    assert [f.code for f in wash_findings({}, 0.8)] == ["wash_fomo_churn"]


def test_wash_lowers_momentum():
    base = {"buyers_10m": 20, "buyers_5m": 10, "buyers_prev_5m": 10}
    clean, _, _ = momentum_score(base, {})
    washed, reasons, _ = momentum_score({**base, "churn_share_30m": 0.6, "transfers_5m": 80, "wallets_5m": 5}, {})
    assert clean - washed == 30
    assert any("sahte hacim" in r for r in reasons)


class FactoryRpc:
    """Serves the factory's launch events; refuses ranges holding more than `cap` logs, like the node."""

    def __init__(self, events, cap=3):
        self.events = events
        self.cap = cap
        self.head = HEAD

    async def block_number(self):
        return self.head

    async def get_logs(self, lo, hi, topics, address=None, retries=4):
        found = [e for e in self.events if lo <= int(e["blockNumber"], 16) <= hi
                 and (len(topics) < 2 or topics[1] is None or e["topics"][1] == topics[1])]
        if len(found) > self.cap:
            raise RuntimeError("logs matched by query exceeds limit")
        return found


async def test_launch_index_backfills_and_answers_history():
    import sqlite3

    from rhscanner.launches import LaunchIndex

    old = [f"0x{i + 1:040x}" for i in range(8)]
    events = [launch_event(t, HEAD - 1000 - i * 300) for i, t in enumerate(old)]  # dense: forces splits
    events += [launch_event("0x" + "d" * 40, HEAD - 50, launcher="0x" + "2" * 40)]
    rpc = FactoryRpc(events)
    index = LaunchIndex(sqlite3.connect(":memory:"), lookback=300_000)
    await index.sync(rpc, backfill_steps=1)
    assert not index.covers(HEAD - 300_000)
    while not index.covers(HEAD - 300_000):
        await index.sync(rpc)
    assert index.count() == 9
    assert index.launcher_of(old[0].upper().replace("0X", "0x")) == LAUNCHER

    rpc.events.append(launch_event(TOKEN, HEAD + 5))  # launched after the last sync: found via the node
    rpc.head = HEAD + 10
    data, findings = await check_deployer(rpc, None, TOKEN, HEAD + 5, index)
    assert data["previous_launches"] == 8 and "partial" not in data
    assert "serial_launcher" not in {f.code for f in findings}
    assert "repeat_launcher" in {f.code for f in findings}
