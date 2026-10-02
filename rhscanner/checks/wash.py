"""Wash trading: volume that is really a few wallets trading with themselves.

Two views, both cheap:
  on-chain  the token's Transfer logs of the last ~5 minutes: how many distinct
            wallets take part, and how much of the activity the busiest wallet
            accounts for (pools, routers and other contracts are left out)
  Fomo      share of Fomo volume from wallets that both bought and sold the
            token repeatedly within 30 minutes (churn)
Research on launchpads puts ~21% of pre-migration trades down to wash trading.
"""

from collections import Counter

from ..rpc import RpcClient
from . import DEAD_ADDRESSES, Finding

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
RECENT_BLOCKS = 3000  # ~5 minutes
TOP_CHECKED = 6


async def recent_flow(rpc: RpcClient, token: str, exclude: set[str]) -> dict:
    head = await rpc.block_number()
    try:
        logs = await rpc.get_logs(head - RECENT_BLOCKS, head, [TRANSFER_TOPIC], address=token, retries=1)
    except Exception:
        return {}
    exclude = {a.lower() for a in exclude} | DEAD_ADDRESSES | {token.lower()}
    seen: Counter[str] = Counter()
    for entry in logs:
        topics = entry.get("topics") or []
        if len(topics) < 3:
            continue
        for addr in ("0x" + topics[1][-40:], "0x" + topics[2][-40:]):
            if addr not in exclude:
                seen[addr] += 1
    # the busiest counterparties are usually pools and routers: drop the contracts among them
    for addr, _ in seen.most_common(TOP_CHECKED):
        code = await rpc.get_code(addr)
        if len(code) > 2 and not code.lower().startswith("0xef0100"):
            del seen[addr]
    wallets = len(seen)
    top = seen.most_common(1)[0][1] if seen else 0
    return {
        "transfers_5m": len(logs),
        "wallets_5m": wallets,
        "top_wallet_share_5m": round(top / max(len(logs), 1), 3),
    }


def fomo_churn(tracker, token: str, window_sec: float = 1800, now: float | None = None) -> float | None:
    """Share of Fomo USD volume from wallets with >=2 buys and >=2 sells of this token in the window."""
    import time

    now = now or time.time()
    trades = [t for t in tracker.trades.get(token.lower(), ()) if t.timestamp > now - window_sec]
    if not trades:
        return None
    buys, sells = Counter(), Counter()
    for t in trades:
        (buys if t.side == "buy" else sells)[t.trader] += 1
    churners = {w for w in buys if buys[w] >= 2 and sells[w] >= 2}
    total = sum(t.usd or 0 for t in trades)
    churn = sum(t.usd or 0 for t in trades if t.trader in churners)
    return round(churn / total, 3) if total else None


def wash_findings(flow: dict, churn: float | None) -> list[Finding]:
    findings = []
    transfers, wallets = flow.get("transfers_5m", 0), flow.get("wallets_5m", 0)
    if transfers >= 50 and wallets <= 8:
        findings.append(Finding("medium", "wash_few_wallets",
                                f"Sahte hacim şüphesi: son 5 dk {transfers} transfer ama sadece {wallets} cüzdan"))
    elif transfers >= 30 and flow.get("top_wallet_share_5m", 0) >= 0.4:
        findings.append(Finding("medium", "wash_one_wallet",
                                f"Sahte hacim şüphesi: son 5 dk transferlerin %{flow['top_wallet_share_5m'] * 100:.0f}'inde aynı cüzdan"))
    if churn is not None and churn >= 0.4:
        findings.append(Finding("medium", "wash_fomo_churn",
                                f"Fomo hacminin %{churn * 100:.0f}'i aynı coini tekrar tekrar alıp satan cüzdanlardan"))
    return findings
