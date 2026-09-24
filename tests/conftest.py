import sys
from pathlib import Path

import pytest
from eth_tester.exceptions import TransactionFailed

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evm import LocalChain  # noqa: E402

from rhscanner.checks.honeypot import PROBE_ADDRESS  # noqa: E402
from rhscanner.rpc import RpcClient, RpcError  # noqa: E402


class EvmRpc(RpcClient):
    """RpcClient backed by a local py-evm chain instead of HTTP.

    eth-tester has no state overrides, so calls to the probe address are sent
    to a normally deployed, pre-funded HoneypotProbe instead.
    """

    def __init__(self, chain: LocalChain, probe_address: str | None = None):
        super().__init__("http://unused", max_rps=0)
        self.chain = chain
        self.probe_address = probe_address

    async def request(self, method, params, retries=0):
        t = self.chain.t
        if method == "eth_call":
            tx = dict(params[0])
            if self.probe_address and tx["to"].lower() == PROBE_ADDRESS:
                tx["to"] = self.probe_address
            tx["from"] = self.chain.owner  # py-evm checks gas funds; real nodes do not
            try:
                return t.call(tx)
            except TransactionFailed as exc:
                raise RpcError(str(exc)) from exc
        if method == "eth_getCode":
            return t.get_code(params[0])
        if method == "eth_getStorageAt":
            return "0x" + t.get_storage_at(params[0], params[1])[2:].rjust(64, "0")
        if method == "eth_getLogs":
            q = params[0]
            fid = t.create_log_filter(
                from_block=int(q["fromBlock"], 16), to_block=int(q["toBlock"], 16),
                address=q.get("address"), topics=q.get("topics"),
            )
            logs = t.get_logs(fid)
            t.delete_filter(fid)
            return [{
                "address": entry["address"], "topics": list(entry["topics"]), "data": entry["data"],
                "blockNumber": hex(entry["block_number"]), "transactionHash": entry["transaction_hash"],
            } for entry in logs]
        if method == "eth_blockNumber":
            return hex(t.get_block_by_number("latest")["number"])
        raise NotImplementedError(method)


def build_market(buy_tax=0, sell_tax=0, block_sells=False, renounce=False, holders=0):
    """Deploy WETH, a tax token and a funded V2 pair; returns (chain, addresses dict)."""
    c = LocalChain()
    weth = c.deploy("MockWETH")
    token = c.deploy("TaxToken", ["uint256"], [10**27])
    pair = c.deploy("MockPair", ["address", "address"], [weth, token])
    c.send(token, "configure(address,uint256,uint256,bool)", ["address", "uint256", "uint256", "bool"],
           [pair, buy_tax, sell_tax, block_sells])
    c.send(weth, "deposit()", [], [], value=10 * 10**18)
    c.send(weth, "transfer(address,uint256)", ["address", "uint256"], [pair, 10 * 10**18])
    c.send(token, "transfer(address,uint256)", ["address", "uint256"], [pair, 10**26])
    c.send(pair, "sync()", [], [])
    probe = c.deploy("HoneypotProbe")
    c.t.send_transaction({"from": c.owner, "to": probe, "value": 10**18, "gas": 100_000})
    for i in range(holders):  # spread 90% of the supply evenly over `holders` wallets
        wallet = "0x" + f"{i + 1:040x}"
        c.send(token, "transfer(address,uint256)", ["address", "uint256"], [wallet, 9 * 10**26 // holders])
    if renounce:
        c.send(token, "renounceOwnership()", [], [])
    return c, {"weth": weth, "token": token, "pair": pair, "probe": probe}


@pytest.fixture
def market_factory():
    return build_market
