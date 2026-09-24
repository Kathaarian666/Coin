"""A tiny local EVM (py-evm via eth-tester) for exercising the Solidity probe."""

import json
from pathlib import Path

from eth_abi import decode, encode
from eth_tester import EthereumTester, PyEVMBackend
from eth_utils import function_signature_to_4byte_selector, to_checksum_address

BUILD = Path(__file__).resolve().parent.parent / "contracts" / "build"


def artifact(name: str) -> dict:
    return json.loads((BUILD / f"{name}.json").read_text())


def calldata(signature: str, types: list[str], args: list) -> str:
    return "0x" + (function_signature_to_4byte_selector(signature) + encode(types, args)).hex()


class LocalChain:
    def __init__(self):
        self.t = EthereumTester(PyEVMBackend())
        self.owner = self.t.get_accounts()[0]
        self.user = self.t.get_accounts()[1]

    def deploy(self, name: str, types: list[str] = (), args: list = ()) -> str:
        data = artifact(name)["bytecode"] + encode(list(types), list(args)).hex()
        tx = self.t.send_transaction({"from": self.owner, "data": data, "gas": 6_000_000})
        return to_checksum_address(self.t.get_transaction_receipt(tx)["contract_address"])

    def send(self, to: str, signature: str, types: list[str], args: list, value: int = 0, sender=None):
        return self.t.send_transaction({
            "from": sender or self.owner, "to": to, "gas": 3_000_000, "value": value,
            "data": calldata(signature, types, args),
        })

    def call(self, to: str, signature: str, types: list[str], args: list, out: list[str]):
        raw = self.t.call({"from": self.owner, "to": to, "data": calldata(signature, types, args)})
        return decode(out, bytes.fromhex(raw[2:]) if isinstance(raw, str) else raw)
