"""Entry point.

  python -m rhscanner              run the Telegram bot + scanner
  python -m rhscanner check 0x...  analyse one token and print the report
"""

import asyncio
import json
import logging
import sys

import httpx

from .analyzer import Analyzer
from .bot import ScannerApp
from .config import Settings
from .rpc import RpcClient
from .sources import Blockscout, DexScreener
from .storage import Storage


async def _check(settings: Settings, token: str):
    async with httpx.AsyncClient(timeout=20) as http:
        rpc = RpcClient(settings.rpc_url, settings.rpc_max_rps)
        storage = Storage(settings.db_path)
        analyzer = Analyzer(
            rpc, settings, Blockscout(settings.blockscout_url, http),
            DexScreener(http) if settings.use_dexscreener else None, storage,
        )
        try:
            print(json.dumps(await analyzer.analyze(token), indent=2, ensure_ascii=False, default=str))
        finally:
            await rpc.close()
            storage.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if len(sys.argv) >= 3 and sys.argv[1] == "check":
        asyncio.run(_check(settings, sys.argv[2]))
    else:
        ScannerApp(settings).run()


if __name__ == "__main__":
    main()
