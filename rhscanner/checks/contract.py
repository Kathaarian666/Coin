"""Contract-level checks: code, proxies, ownership, risky admin functions, verification."""

from eth_utils import keccak

from ..rpc import RpcClient
from ..sources import Blockscout
from . import DEAD_ADDRESSES, Finding

EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
EIP1167_PREFIX = "363d3d373d3d3d363d73"

# Admin functions that let an owner hurt holders, grouped by what they allow.
RISKY_FUNCTIONS = {
    "mint": ["mint(address,uint256)", "mint(uint256)", "mintTo(address,uint256)"],
    "blacklist": [
        "blacklist(address)", "addToBlacklist(address)", "setBlacklist(address,bool)",
        "blacklistAddress(address,bool)", "addBots(address[])", "setBots(address[],bool)",
        "setBot(address,bool)", "blockBots(address[])",
    ],
    "fees": [
        "setFee(uint256)", "setFees(uint256,uint256)", "setTaxFee(uint256)", "setBuyFee(uint256)",
        "setSellFee(uint256)", "setTaxes(uint256,uint256)", "updateFees(uint256,uint256)",
        "setBuyTax(uint256)", "setSellTax(uint256)", "updateBuyFees(uint256,uint256,uint256)",
        "updateSellFees(uint256,uint256,uint256)",
    ],
    "pause": ["pause()", "setPaused(bool)"],
    "limits": [
        "setMaxTxAmount(uint256)", "setMaxWallet(uint256)", "setMaxTxPercent(uint256)",
        "updateMaxTxnAmount(uint256)", "updateMaxWalletAmount(uint256)",
    ],
    "trading": ["enableTrading()", "openTrading()", "setTradingEnabled(bool)"],
    "upgrade": ["upgradeTo(address)", "upgradeToAndCall(address,bytes)"],
}

RISK_TEXT = {
    "mint": ("high", "Sahip yeni token basabilir (mint) — arz sınırsız artırılabilir"),
    "blacklist": ("high", "Kara liste fonksiyonu var — cüzdanınız satıştan engellenebilir"),
    "fees": ("high", "Vergi oranları sonradan değiştirilebilir — satış vergisi %100'e çekilebilir"),
    "pause": ("high", "Transferler durdurulabilir (pause)"),
    "limits": ("medium", "Maks. işlem/cüzdan limiti değiştirilebilir — satış kısıtlanabilir"),
    "trading": ("low", "Trading aç/kapa fonksiyonu var"),
    "upgrade": ("high", "Kontrat yükseltilebilir — kod sonradan değiştirilebilir"),
}


def _selector(signature: str) -> str:
    return keccak(text=signature)[:4].hex()


RISKY_SELECTORS = {group: {_selector(s): s for s in sigs} for group, sigs in RISKY_FUNCTIONS.items()}


def find_risky_functions(code_hex: str) -> dict[str, list[str]]:
    """Look for PUSH4 <selector> in the dispatcher, the usual heuristic for bytecode ABIs."""
    code = code_hex.lower().removeprefix("0x")
    found = {}
    for group, selectors in RISKY_SELECTORS.items():
        hits = [sig for sel, sig in selectors.items() if "63" + sel in code]
        if hits:
            found[group] = hits
    return found


def _slot_address(value: str | None) -> str | None:
    if not value or int(value, 16) == 0:
        return None
    return "0x" + value[-40:]


async def check_contract(rpc: RpcClient, blockscout: Blockscout | None, token: str) -> tuple[dict, list[Finding]]:
    findings: list[Finding] = []
    data: dict = {}

    code = await rpc.get_code(token)
    if not code or code == "0x":
        return data, [Finding("critical", "no_code", "Adreste kontrat kodu yok")]

    analysed_code = code
    body = code.lower().removeprefix("0x")
    if body.startswith(EIP1167_PREFIX):
        impl = "0x" + body[len(EIP1167_PREFIX): len(EIP1167_PREFIX) + 40]
        data["clone_of"] = impl
        analysed_code = await rpc.get_code(impl)
        findings.append(Finding("info", "clone", "Standart bir şablonun klonu (değiştirilemez)"))

    impl = _slot_address(await rpc.get_storage_at(token, EIP1967_IMPL_SLOT))
    beacon = _slot_address(await rpc.get_storage_at(token, EIP1967_BEACON_SLOT))
    if impl or beacon:
        data["proxy_implementation"] = impl or beacon
        findings.append(Finding("high", "upgradeable", "Yükseltilebilir proxy — geliştirici kodu değiştirebilir"))
        if impl:
            analysed_code = await rpc.get_code(impl)

    owner = None
    for fn in ("owner()", "getOwner()"):
        result = await rpc.try_call_fn(token, fn, ["address"])
        if result:
            owner = result[0].lower()
            break
    data["owner"] = owner
    renounced = owner is None or owner in DEAD_ADDRESSES
    data["renounced"] = renounced
    if owner is None:
        findings.append(Finding("info", "no_owner_fn", "owner() fonksiyonu yok"))
    elif renounced:
        findings.append(Finding("good", "renounced", "Sahiplik devredilmiş (renounced)"))
    elif len(await rpc.get_code(owner)) > 2:
        data["owner_is_contract"] = True
        findings.append(Finding("low", "owned_by_contract", f"Sahibi bir kontrat (launchpad/multisig olabilir): {owner}"))
    else:
        findings.append(Finding("medium", "owned", f"Kontratın hâlâ bir sahibi var: {owner}"))

    risky = find_risky_functions(analysed_code)
    data["risky_functions"] = risky
    for group in risky:
        severity, text = RISK_TEXT[group]
        if renounced and group != "upgrade":
            # With no owner these admin functions can no longer be called.
            findings.append(Finding("info", f"fn_{group}_inactive", f"{text} (sahip yok, etkisiz)"))
        else:
            findings.append(Finding(severity, f"fn_{group}", text))

    if blockscout:
        info = await blockscout.smart_contract(token)
        if info is not None:  # None = explorer unreachable, which says nothing about the token
            verified = bool(info.get("is_verified"))
            data["verified"] = verified
            if verified:
                findings.append(Finding("good", "verified", "Kaynak kodu doğrulanmış (verified)"))
            else:
                findings.append(Finding("medium", "unverified", "Kaynak kodu doğrulanmamış — kod okunamıyor"))
        addr = await blockscout.address_info(token)
        if addr:
            data["creator"] = (addr.get("creator_address_hash") or "").lower() or None

    return data, findings
