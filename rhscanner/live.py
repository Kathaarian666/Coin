"""Real alerts (PROJE.md §1, step 4), behind /canli (off by default): the paper test's picks, sent to Telegram.

Before a pick is sent it must not be unsellable (the user's only elimination rule): a Pons coin passes (its
template cannot block sells), any other coin is sold in a simulation into its Uniswap V4 pool by a real holder
(contracts/V4SellProbe.sol through an eth_call state override, nothing is spent). A revert or a transfer tax of
10 % or more drops the pick; when nothing can be simulated (no pool or holder found) it is sent with a warning.
The message gives the 2x chance (what the top 2 % did in the walk-forward test) and the 3 criteria that lift the
score most; the safety report with the trust score (trust_model.json, PROJE.md §4.1) follows as a reply.
Afterwards: "2x oldu" when two buys in a row reach 2x the alert price, and a warning when liquidity is taken out
of the coin's V4 pool (ModifyLiquidity with a negative delta).
"""

import json
import math
from pathlib import Path

from eth_abi import decode, encode
from eth_utils import function_signature_to_4byte_selector, keccak, to_checksum_address

from .hooks import NAMED_HOOKS, TOPIC_V4_INITIALIZE

TRUST_PATH = Path(__file__).with_name("trust_model.json")
PROBE_PATH = Path(__file__).resolve().parents[1] / "contracts" / "build" / "V4SellProbe.json"
PROBE_CALLER = "0x00000000000000000000000000000000c0ffee02"
SELL_SIG = "sell(address,(address,address,uint24,int24,address),address,uint256)"
TOPIC_MODIFY_LIQUIDITY = "0x" + keccak(text="ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)").hex()
ZERO = "0x" + "0" * 40
POOL_LOOKBACK = 2 * 864_000  # blocks (~2 days) searched for the coin's V4 pool
MAX_TAX = 0.10
LIQ_WATCH = 6 * 3600  # s after the alert the pool is watched for liquidity removal

LABELS = {  # criterion -> (Turkish name, how to show its value)
    "mins_to_k": ("5. alıcıya kadar geçen süre", lambda v: f"{v:.1f} dk"),
    "trades_to_k": ("işlem sayısı", lambda v: f"{v:.0f}"),
    "usd_all": ("toplam alım", lambda v: f"${v:,.0f}"),
    "usd_per_trade": ("işlem başına alım", lambda v: f"${v:,.0f}"),
    "max_buy": ("en büyük alım", lambda v: f"${v:,.0f}"),
    "sellers": ("satıcı sayısı", lambda v: f"{v:.0f}"),
    "early_sold": ("ilk alıcılardan satan", lambda v: f"%{100 * v:.0f}"),
    "sell_usd_share": ("satış payı", lambda v: f"%{100 * v:.0f}"),
    "buyers_5m": ("son 5 dk alıcı", lambda v: f"{v:.0f}"),
    "usd_10m": ("son 10 dk alım", lambda v: f"${v:,.0f}"),
    "runup": ("ilk alımdan bu yana fiyat", lambda v: f"{v:.2f}x"),
    "off_high": ("zirveye göre fiyat", lambda v: f"{v:.2f}x"),
    "fdv": ("piyasa değeri", lambda v: f"${v:,.0f}"),
    "launch_age_min": ("lansmandan bu yana", lambda v: f"{v:.0f} dk"),
    "depth_usd": ("havuz derinliği", lambda v: f"${v:,.0f}"),
    "buyers_60s": ("son 60 sn alıcı", lambda v: f"{v:.0f}"),
    "usd_60s_share": ("son 60 sn alım payı", lambda v: f"%{100 * v:.0f}"),
    "same_block_buys": ("aynı blokta alım", lambda v: f"{v:.0f}"),
    "small_buy_share": ("küçük alım payı", lambda v: f"%{100 * v:.0f}"),
    "buyers_hit_rate": ("ilk alıcıların geçmiş 2x oranı", lambda v: f"%{100 * v:.0f}"),
}


def reasons(model, features: dict, n: int = 3) -> list[tuple[str, str]]:
    """The criteria whose typical value would lower the score most: (name, this coin's value)."""
    medians = getattr(model, "medians", None) or {}
    base = model.score(features)
    drops = []
    for f in model.features:
        v = features.get(f)
        if f not in medians or v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        drop = base - model.score({**features, f: medians[f]})
        if drop > 0:
            drops.append((drop, f, v))
    drops.sort(reverse=True)
    return [(LABELS.get(f, (f, str))[0], LABELS.get(f, (f, lambda x: f"{x:g}"))[1](v)) for _, f, v in drops[:n]]


# --- trust score (PROJE.md §4.1) ---
def trust_flags(report: dict, fomo_sellers: int, pons: bool, depth: float | None) -> dict:
    codes = {f["code"] for f in report.get("findings", [])}
    hooks = (report.get("liquidity") or {}).get("hooks")
    named = {h.lower() for h in NAMED_HOOKS}
    return {
        "satici2": int(fomo_sellers >= 2),
        "proxy": int(bool((report.get("contract") or {}).get("proxy_implementation"))),
        "sahip": int(bool(codes & {"owned", "owned_by_contract"})),
        "mint": int("fn_mint" in codes),
        "pause": int("fn_pause" in codes),
        "trading": int("fn_trading" in codes),
        "dev5": int(((report.get("launch") or {}).get("dev_pct") or 0) > 5),
        "hook_yok": int(hooks == ZERO),
        "hook_baska": int(bool(hooks) and hooks != ZERO and hooks not in named),
        "liq1k": int(depth is not None and not math.isnan(depth) and 2 * depth < 1000),
        "pons_or_hook": int(pons or (bool(hooks) and hooks in named)),
    }


def trust_score(flags: dict, path: Path = TRUST_PATH) -> int | None:
    if not Path(path).exists():
        return None
    m = json.loads(Path(path).read_text())
    z = m["intercept"] + sum(m["coef"].get(k, 0.0) * v for k, v in flags.items())
    p = 1 / (1 + math.exp(-z))
    return int(round(max(0.0, min(100.0, 100 * (1 - p / m["half"])))))


# --- can it be sold? ---
async def find_pool(rpc, pm: str, token: str, head: int) -> tuple[str, tuple] | None:
    """The coin's latest V4 pool: (pool id, key (currency0, currency1, fee, tickSpacing, hooks))."""
    topic = "0x" + "0" * 24 + token.lower()[2:]
    found = []
    for topics in ([TOPIC_V4_INITIALIZE, None, topic], [TOPIC_V4_INITIALIZE, None, None, topic]):
        for e in await rpc.get_logs(max(0, head - POOL_LOOKBACK), head, topics, address=pm):
            d = bytes.fromhex(e["data"][2:])
            key = ("0x" + e["topics"][2][-40:], "0x" + e["topics"][3][-40:], int.from_bytes(d[0:32], "big"),
                   int.from_bytes(d[32:64], "big", signed=True), "0x" + d[76:96].hex())
            found.append((int(e["blockNumber"], 16), e["topics"][1], key))
    if not found:
        return None
    _, pool_id, key = max(found)
    return pool_id, key


async def sell_check(rpc, pm: str, token: str, key: tuple, holders: list[str]) -> tuple[str, str]:
    """('ok' | 'honeypot' | 'vergi' | 'bilinmiyor', detail): a holder sells a tenth of its coins into the pool."""
    code = json.loads(PROBE_PATH.read_text())["deployedBytecode"]
    selector = function_signature_to_4byte_selector(SELL_SIG)
    pm = to_checksum_address(pm)
    for holder in holders:
        bal = await rpc.try_call_fn(token, "balanceOf(address)", ["uint256"], ["address"], [holder])
        if not bal or not bal[0]:
            continue
        args = encode(["address", "(address,address,uint24,int24,address)", "address", "uint256"],
                      [pm, (to_checksum_address(key[0]), to_checksum_address(key[1]), key[2], key[3],
                            to_checksum_address(key[4])), to_checksum_address(token), max(1, bal[0] // 10)])
        try:
            raw = await rpc.eth_call(to_checksum_address(holder), "0x" + (selector + args).hex(),
                                     overrides={to_checksum_address(holder): {"code": code}}, sender=PROBE_CALLER)
        except Exception as exc:
            return "bilinmiyor", f"simülasyon çalışmadı ({str(exc)[:60]})"
        (sent, arrived, out, _used), failed, _reason = decode(["(uint256,uint256,uint256,uint256)", "uint8", "bytes"],
                                                               bytes.fromhex(raw[2:]))
        if failed:
            return "honeypot", "satış simülasyonu geri döndü"
        tax = 1 - arrived / sent if sent else 0.0
        if tax >= MAX_TAX:
            return "vergi", f"satış vergisi %{100 * tax:.0f}"
        if out == 0:
            return "bilinmiyor", "satış karşılığı 0 (likidite yok)"
        return "ok", f"satış simülasyonu geçti (vergi %{100 * tax:.0f})"
    return "bilinmiyor", "bakiyesi olan alıcı bulunamadı"


async def sell_gate(rpc, pm: str, token: str, pons: bool, buyers: list[str]) -> tuple[str, str, str | None]:
    """(status, detail, pool id). Pons coins pass; others need the V4 sell simulation."""
    if pons:
        return "ok", "Pons launchpad coini (şablonu satışı engelleyemez)", None
    head = await rpc.block_number()
    pool = await find_pool(rpc, pm, token, head)
    if pool is None:
        return "bilinmiyor", "V4 havuzu bulunamadı", None
    status, detail = await sell_check(rpc, pm, token, pool[1], list(dict.fromkeys(reversed(buyers)))[:5])
    return status, detail, pool[0]


async def liquidity_removed(rpc, pm: str, pool_id: str, from_block: int, to_block: int) -> int:
    """Number of ModifyLiquidity events with a negative delta (liquidity taken out) in the block range."""
    logs = await rpc.get_logs(from_block, to_block, [TOPIC_MODIFY_LIQUIDITY, pool_id], address=pm)
    out = 0
    for e in logs:
        d = bytes.fromhex(e["data"][2:])
        if len(d) >= 96 and int.from_bytes(d[64:96], "big", signed=True) < 0:
            out += 1
    return out


class LiveLog:
    """Sent alerts and their follow-ups."""

    def __init__(self, db):
        self.db = db
        db.execute("""CREATE TABLE IF NOT EXISTS live_log (token TEXT PRIMARY KEY, ts REAL, p_alert REAL, block INTEGER,
                      pool TEXT, msg TEXT, gate TEXT, sent_2x INTEGER DEFAULT 0, warned INTEGER DEFAULT 0,
                      checked_block INTEGER)""")
        db.commit()

    def add(self, token, ts, p_alert, block, pool, msg, gate):
        self.db.execute("INSERT OR REPLACE INTO live_log (token, ts, p_alert, block, pool, msg, gate, checked_block) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (token, ts, p_alert, block, pool, json.dumps(msg), gate, block))
        self.db.commit()

    def open(self, now: float) -> list[dict]:
        cur = self.db.execute("SELECT * FROM live_log WHERE ts >= ? AND (sent_2x = 0 OR warned = 0)", (now - 3 * 86400,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def mark(self, token: str, **fields):
        for k, v in fields.items():
            self.db.execute(f"UPDATE live_log SET {k} = ? WHERE token = ?", (v, token))
        self.db.commit()
