"""Entry point.

  python -m rhscanner              run the Telegram bot + scanners
  python -m rhscanner check 0x...  analyse one token and print the report
  python -m rhscanner trend        print the tokens most bought on Fomo recently
"""

import asyncio
import json
import logging
import sys
import time

import httpx

from .analyzer import Analyzer
from .bot import ScannerApp
from .config import Settings
from .fomo import FomoTracker, fetch_fomo_logs, parse_fomo_logs
from .report import format_report
from .rpc import RpcClient
from .sources import Blockscout, DexScreener
from .storage import Storage


def _analyzer(settings: Settings, rpc: RpcClient, http: httpx.AsyncClient, storage: Storage) -> Analyzer:
    return Analyzer(
        rpc, settings, Blockscout(settings.blockscout_url, http),
        DexScreener(http) if settings.use_dexscreener else None, storage,
    )


async def _check(settings: Settings, token: str):
    async with httpx.AsyncClient(timeout=20) as http:
        rpc = RpcClient(settings.rpc_url, settings.rpc_max_rps, fallback_urls=settings.rpc_fallback_urls)
        storage = Storage(settings.db_path)
        try:
            report = await _analyzer(settings, rpc, http, storage).analyze(token)
            print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        finally:
            await rpc.close()
            storage.close()


async def _trend(settings: Settings, analyze_top: int):
    rpc = RpcClient(settings.rpc_url, settings.rpc_max_rps, fallback_urls=settings.rpc_fallback_urls)
    tracker = FomoTracker()
    head = await rpc.block_number()
    start = head - settings.fomo_lookback_blocks
    for lo in range(start, head + 1, 3000):
        logs = await fetch_fomo_logs(rpc, lo, min(head, lo + 2999))
        for trade in parse_fomo_logs(logs):
            trade.timestamp = time.time()
            tracker.add(trade)
    minutes = settings.fomo_lookback_blocks / 10 / 60
    print(f"Fomo (Robinhood Chain) — son ~{minutes:.0f} dk, en çok alınanlar:\n")
    rows = tracker.top(10**9, limit=15)
    for i, (token, s) in enumerate(rows, 1):
        symbol = await rpc.try_call_fn(token, "symbol()", ["string"])
        print(f"{i:2}. {(symbol[0] if symbol else '?'):<12} {s['buyers']:3} alıcı {s['sellers']:3} satıcı  "
              f"alım ${s['buy_usd']:>9,.0f}  satış ${s['sell_usd']:>9,.0f}  {token}")
    if analyze_top:
        async with httpx.AsyncClient(timeout=20) as http:
            storage = Storage(settings.db_path)
            analyzer = _analyzer(settings, rpc, http, storage)
            for token, stats in rows[:analyze_top]:
                stats["window_min"] = round(minutes)
                report = await analyzer.analyze(token, fomo=stats)
                print("\n" + format_report(report, settings.blockscout_url, "🔥 Fomo'da yükselen token"))
            storage.close()
    await rpc.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if len(sys.argv) >= 3 and sys.argv[1] == "check":
        asyncio.run(_check(settings, sys.argv[2]))
    elif len(sys.argv) >= 2 and sys.argv[1] == "trend":
        analyze_top = int(sys.argv[2]) if len(sys.argv) >= 3 else 0
        asyncio.run(_trend(settings, analyze_top))
    else:
        ScannerApp(settings).run()


if __name__ == "__main__":
    main()
