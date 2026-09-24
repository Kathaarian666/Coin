"""Settings, read from environment variables (and a local .env file)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Robinhood Chain mainnet (Arbitrum Orbit L2, gas paid in ETH).
CHAIN_ID = 4663
DEFAULT_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
# Used when the main RPC rate-limits or fails. dRPC's free tier needs no key but
# only serves eth_getLogs over short ranges, which the scanners split down to.
DEFAULT_RPC_FALLBACK_URLS = "https://robinhood.drpc.org"
DEFAULT_BLOCKSCOUT_URL = "https://robinhoodchain.blockscout.com"
DEFAULT_WETH = "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
DEXSCREENER_CHAIN = "robinhood"
# Global Dollar: the stablecoin Fomo balances are held and traded in.
USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
DEFAULT_V4_POOL_MANAGER = "0x8366a39CC670B4001A1121B8F6A443A643e40951"


def _flag(value: str) -> bool:
    return value.strip().lower() not in ("0", "false", "no", "")


def _list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    telegram_token: str = ""
    telegram_chat_ids: list[int] = field(default_factory=list)
    rpc_url: str = DEFAULT_RPC_URL
    rpc_fallback_urls: list[str] = field(default_factory=lambda: _list(DEFAULT_RPC_FALLBACK_URLS))
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
    rpc_max_rps: float = 6.0
    analysis_delay: float = 8.0
    analysis_workers: int = 2
    probe_eth: float = 0.005
    min_score_alert: int = 50
    use_dexscreener: bool = True
    v4_pool_manager: str = DEFAULT_V4_POOL_MANAGER
    # How far back (in blocks, ~10/s) to look for a token's transfers when ranking holders.
    holder_lookback_blocks: int = 30_000_000
    # Fomo order-flow watcher: alert when a token gets enough distinct Fomo buyers.
    enable_fomo_watcher: bool = True
    fomo_window_min: float = 10.0
    fomo_min_buyers: int = 10
    # ...and at least this much bought through Fomo in the window (median Fomo buy is ~$20).
    fomo_min_buy_usd: float = 500.0
    fomo_lookback_blocks: int = 6000
    # Raw new-pool watcher: every new DEX pool, Fomo or not (very noisy).
    enable_pool_watcher: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = os.environ.get
        return cls(
            telegram_token=env("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_ids=[int(x) for x in _list(env("TELEGRAM_CHAT_IDS", ""))],
            rpc_url=env("RPC_URL", DEFAULT_RPC_URL),
            rpc_fallback_urls=_list(env("RPC_FALLBACK_URLS", DEFAULT_RPC_FALLBACK_URLS)),
            blockscout_url=env("BLOCKSCOUT_URL", DEFAULT_BLOCKSCOUT_URL).rstrip("/"),
            weth=env("WETH_ADDRESS", DEFAULT_WETH),
            extra_quote_tokens=[a.lower() for a in _list(env("EXTRA_QUOTE_TOKENS", ""))],
            factory_allowlist=[a.lower() for a in _list(env("FACTORY_ALLOWLIST", ""))],
            db_path=env("DB_PATH", "rhscanner.db"),
            poll_interval=float(env("POLL_INTERVAL", "3")),
            max_block_range=int(env("MAX_BLOCK_RANGE", "2000")),
            start_lookback_blocks=int(env("START_LOOKBACK_BLOCKS", "0")),
            rpc_max_rps=float(env("RPC_MAX_RPS", "6")),
            analysis_delay=float(env("ANALYSIS_DELAY", "8")),
            analysis_workers=int(env("ANALYSIS_WORKERS", "2")),
            probe_eth=float(env("PROBE_ETH", "0.005")),
            min_score_alert=int(env("MIN_SCORE_ALERT", "50")),
            use_dexscreener=_flag(env("USE_DEXSCREENER", "1")),
            v4_pool_manager=env("V4_POOL_MANAGER", DEFAULT_V4_POOL_MANAGER),
            holder_lookback_blocks=int(env("HOLDER_LOOKBACK_BLOCKS", "30000000")),
            enable_fomo_watcher=_flag(env("ENABLE_FOMO_WATCHER", "1")),
            fomo_window_min=float(env("FOMO_WINDOW_MIN", "10")),
            fomo_min_buyers=int(env("FOMO_MIN_BUYERS", "10")),
            fomo_min_buy_usd=float(env("FOMO_MIN_BUY_USD", "500")),
            fomo_lookback_blocks=int(env("FOMO_LOOKBACK_BLOCKS", "6000")),
            enable_pool_watcher=_flag(env("ENABLE_POOL_WATCHER", "0")),
        )

    @property
    def quote_tokens(self) -> set[str]:
        # The zero address stands for native ETH in Uniswap V4 pools.
        return {self.weth.lower(), "0x" + "0" * 40, USDG.lower(), *self.extra_quote_tokens}
