from types import SimpleNamespace

from eth_abi import encode

from conftest import EvmRpc
from rhscanner.analyzer import Analyzer, pool_from_dexscreener
from rhscanner.discovery import TOPIC_V2_PAIR_CREATED, PoolWatcher
from rhscanner.storage import Storage


def settings(weth, **kw):
    base = dict(weth=weth, quote_tokens={weth.lower(), "0x" + "0" * 40}, probe_eth=0.01,
                factory_allowlist=[], start_lookback_blocks=0, max_block_range=100, poll_interval=0)
    base.update(kw)
    return SimpleNamespace(**base)


async def analyze(chain, addrs, tmp_path):
    analyzer = Analyzer(EvmRpc(chain, addrs["probe"]), settings(addrs["weth"]), None, None,
                        Storage(str(tmp_path / "t.db")))
    pool = {"dex": "v2", "pool": addrs["pair"], "token": addrs["token"], "quote": addrs["weth"]}
    return await analyzer.analyze(addrs["token"], pool)


async def test_honeypot_scores_zero(market_factory, tmp_path):
    chain, addrs = market_factory(block_sells=True, renounce=True)
    report = await analyze(chain, addrs, tmp_path)
    assert report["symbol"] == "?" and report["score"] == 0
    assert any(f["code"] == "honeypot" for f in report["findings"])


async def test_clean_renounced_token_scores_well(market_factory, tmp_path):
    chain, addrs = market_factory(renounce=True)
    report = await analyze(chain, addrs, tmp_path)
    assert report["liquidity"]["liquidity_eth"] > 9
    assert report["honeypot"]["sell_tax"] == 0
    assert report["score"] >= 75


def test_pool_from_dexscreener_picks_deepest_weth_pair():
    weth, token = "0x" + "a" * 40, "0x" + "b" * 40
    pairs = [
        {"pairAddress": "0x1", "baseToken": {"address": token}, "quoteToken": {"address": weth},
         "labels": ["v3"], "liquidity": {"usd": 100}},
        {"pairAddress": "0x2", "baseToken": {"address": weth}, "quoteToken": {"address": token},
         "liquidity": {"usd": 5000}},
        {"pairAddress": "0x3", "baseToken": {"address": token}, "quoteToken": {"address": "0x" + "c" * 40},
         "liquidity": {"usd": 99999}},
    ]
    pool = pool_from_dexscreener(token, pairs, {weth})
    assert pool["pool"] == "0x2" and pool["dex"] == "v2" and pool["quote"] == weth


class LogRpc:
    """Serves one PairCreated log, then stops the watcher loop."""

    def __init__(self, entry, pair_factory):
        self.entry, self.pair_factory, self.calls = entry, pair_factory, 0

    async def block_number(self):
        self.calls += 1
        if self.calls > 2:
            raise KeyboardInterrupt  # escape the infinite loop in the test
        return 100

    async def get_logs(self, from_block, to_block, topics):
        return [self.entry] if from_block <= 100 <= to_block else []

    async def try_call_fn(self, to, signature, out_types, *args):
        return (self.pair_factory,)


async def test_watcher_emits_genuine_pools_and_saves_progress(tmp_path):
    weth, token = "0x" + "a" * 40, "0x" + "b" * 40
    factory, pair = "0x" + "f" * 40, "0x" + "c" * 40
    entry = {"address": factory, "blockNumber": hex(100), "transactionHash": "0x1",
             "topics": [TOPIC_V2_PAIR_CREATED, "0x" + token[2:].rjust(64, "0"), "0x" + weth[2:].rjust(64, "0")],
             "data": "0x" + encode(["address", "uint256"], [pair, 1]).hex()}
    storage = Storage(str(tmp_path / "w.db"))
    storage.set_state("last_block", "90")
    found = []

    async def on_pool(pool):
        found.append(pool)

    async def run(rpc):
        try:
            await PoolWatcher(rpc, settings(weth), storage).run(on_pool)
        except KeyboardInterrupt:
            pass

    await run(LogRpc(entry, factory))
    assert [p.token.lower() for p in found] == [token]
    assert storage.get_state("last_block") == "100"

    # A log from a contract that is not the pair's real factory is rejected.
    found.clear()
    storage.set_state("last_block", "90")
    await run(LogRpc(entry, "0x" + "e" * 40))
    assert found == []


def test_storage_marks_tokens_once(tmp_path):
    storage = Storage(str(tmp_path / "s.db"))
    pool = {"dex": "v2", "pool": "0x1"}
    assert storage.mark_seen("0xABC", pool, 5) is True
    assert storage.mark_seen("0xabc", pool, 6) is False
    assert storage.known_pool("0xAbC") == pool
