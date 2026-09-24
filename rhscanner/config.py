"""Settings, read from environment variables (and a local .env file)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Robinhood Chain mainnet (Arbitrum Orbit L2, gas paid in ETH).
CHAIN_ID = 4663
DEFAULT_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
DEFAULT_BLOCKSCOUT_URL = "https://robinhoodchain.blockscout.com"
DEFAULT_WETH = "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
DEXSCREENER_CHAIN = "robinhood"


def _list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    telegram_token: str = ""
    telegram_chat_ids: list[int] = field(default_factory=list)
    rpc_url: str = DEFAULT_RPC_URL
    blockscout_url: str = DEFAULT_BLOCKSCOUT_URL
    weth: str = DEFAULT_WETH
    # Extra quote tokens (e.g. stablecoins) besides WETH/native ETH, lowercased.
    extra_quote_tokens: list[str] = field(default_factory=list)
    # Only accept pools from these factories/PoolManagers (lowercased); empty = any.
    factory_allowlist: list[str] = field(default_factory=list)
    db_path: str = "rhscanner.db"
    poll_interval: float = 3.0
    max_block_range: int = 2000
    start_lookback_blocks: int = 0
    rpc_max_rps: float = 8.0
    analysis_delay: float = 8.0
    analysis_workers: int = 2
    probe_eth: float = 0.005
    min_score_alert: int = 50
    use_dexscreener: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = os.environ.get
        return cls(
            telegram_token=env("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_ids=[int(x) for x in _list(env("TELEGRAM_CHAT_IDS", ""))],
            rpc_url=env("RPC_URL", DEFAULT_RPC_URL),
            blockscout_url=env("BLOCKSCOUT_URL", DEFAULT_BLOCKSCOUT_URL).rstrip("/"),
            weth=env("WETH_ADDRESS", DEFAULT_WETH),
            extra_quote_tokens=[a.lower() for a in _list(env("EXTRA_QUOTE_TOKENS", ""))],
            factory_allowlist=[a.lower() for a in _list(env("FACTORY_ALLOWLIST", ""))],
            db_path=env("DB_PATH", "rhscanner.db"),
            poll_interval=float(env("POLL_INTERVAL", "3")),
            max_block_range=int(env("MAX_BLOCK_RANGE", "2000")),
            start_lookback_blocks=int(env("START_LOOKBACK_BLOCKS", "0")),
            rpc_max_rps=float(env("RPC_MAX_RPS", "8")),
            analysis_delay=float(env("ANALYSIS_DELAY", "8")),
            analysis_workers=int(env("ANALYSIS_WORKERS", "2")),
            probe_eth=float(env("PROBE_ETH", "0.005")),
            min_score_alert=int(env("MIN_SCORE_ALERT", "50")),
            use_dexscreener=env("USE_DEXSCREENER", "1") not in ("0", "false", "False"),
        )

    @property
    def quote_tokens(self) -> set[str]:
        # The zero address stands for native ETH in Uniswap V4 pools.
        return {self.weth.lower(), "0x" + "0" * 40, *self.extra_quote_tokens}
