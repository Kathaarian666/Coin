from eth_abi import encode

from rhscanner.discovery import (
    TOPIC_V2_PAIR_CREATED, TOPIC_V3_POOL_CREATED, TOPIC_V4_INITIALIZE, parse_log,
)

WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
TOKEN = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
POOL = "0x3333333333333333333333333333333333333333"
FACTORY = "0x4444444444444444444444444444444444444444"
QUOTES = {WETH, "0x" + "0" * 40}


def topic(addr: str) -> str:
    return "0x" + addr[2:].rjust(64, "0")


def log(topics, data: bytes) -> dict:
    return {"address": FACTORY, "topics": topics, "data": "0x" + data.hex(), "blockNumber": "0x10",
            "transactionHash": "0xabc"}


def test_v2_pair_created():
    entry = log([TOPIC_V2_PAIR_CREATED, topic(TOKEN), topic(WETH)], encode(["address", "uint256"], [POOL, 7]))
    pool = parse_log(entry, QUOTES)
    assert pool.dex == "v2" and pool.block == 16
    assert pool.token.lower() == TOKEN and pool.quote.lower() == WETH and pool.pool.lower() == POOL


def test_v3_pool_created_with_weth_as_token0():
    entry = log([TOPIC_V3_POOL_CREATED, topic(WETH), topic(TOKEN), hex(3000)], encode(["int24", "address"], [60, POOL]))
    pool = parse_log(entry, QUOTES)
    assert pool.dex == "v3" and pool.fee == 3000
    assert pool.token.lower() == TOKEN and pool.pool.lower() == POOL


def test_v4_initialize_native_eth_with_hooks():
    pool_id = "0x" + "ab" * 32
    data = encode(["uint24", "int24", "address", "uint160", "int24"], [10000, 200, OTHER, 2**96, 0])
    entry = log([TOPIC_V4_INITIALIZE, pool_id, topic("0x" + "0" * 40), topic(TOKEN)], data)
    pool = parse_log(entry, QUOTES)
    assert pool.dex == "v4" and pool.pool == pool_id
    assert pool.token.lower() == TOKEN and pool.hooks.lower() == OTHER


def test_pairs_without_exactly_one_quote_are_ignored():
    no_quote = log([TOPIC_V2_PAIR_CREATED, topic(TOKEN), topic(OTHER)], encode(["address", "uint256"], [POOL, 1]))
    both_quotes = log([TOPIC_V2_PAIR_CREATED, topic("0x" + "0" * 40), topic(WETH)], encode(["address", "uint256"], [POOL, 1]))
    assert parse_log(no_quote, QUOTES) is None
    assert parse_log(both_quotes, QUOTES) is None


def test_malformed_log_is_ignored():
    assert parse_log(log([TOPIC_V2_PAIR_CREATED, topic(TOKEN), topic(WETH)], b"\x01"), QUOTES) is None
    assert parse_log(log(["0x" + "9" * 64], b""), QUOTES) is None
