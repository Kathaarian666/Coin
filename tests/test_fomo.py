from eth_abi import encode

from rhscanner.analyzer import fomo_findings
from rhscanner.config import USDG
from rhscanner.fomo import FOMO_ENTRY, FOMO_EXECUTOR, FOMO_TRANSFER_TOPIC, FomoTracker, parse_fomo_logs

TOKEN = "0x1111111111111111111111111111111111111111"
USER_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
USER_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
ETH = "0x" + "0" * 40


def leg(emitter, frm, to, token, amount, tx, block=100):
    data = encode(["address", "address", "address", "uint256", "bytes"], [frm, to, token, amount, b"\x01" * 33])
    return {"address": emitter, "topics": [FOMO_TRANSFER_TOPIC], "data": "0x" + data.hex(),
            "blockNumber": hex(block), "transactionHash": tx}


def buy(user, usd, tx):
    return [leg(FOMO_ENTRY, user, FOMO_EXECUTOR, USDG, int(usd * 1e6), tx),
            leg(FOMO_EXECUTOR, FOMO_EXECUTOR, user, TOKEN, 5 * 10**18, tx)]


def sell(user, usd, tx):
    return [leg(FOMO_ENTRY, user, FOMO_EXECUTOR, TOKEN, 5 * 10**18, tx),
            leg(FOMO_EXECUTOR, FOMO_EXECUTOR, FOMO_EXECUTOR, USDG, int(usd * 1e6), tx)]


def test_parse_buys_and_sells():
    logs = buy(USER_A, 25.5, "0x1") + sell(USER_B, 10, "0x2")
    trades = sorted(parse_fomo_logs(logs), key=lambda t: t.side)
    assert [(t.side, t.trader, t.usd) for t in trades] == [("buy", USER_A, 25.5), ("sell", USER_B, 10.0)]
    assert all(t.token.lower() == TOKEN for t in trades)


def test_eth_paid_buy_and_cash_only_legs():
    logs = [leg(FOMO_EXECUTOR, USER_A, FOMO_EXECUTOR, ETH, 10**16, "0x3"),
            leg(FOMO_EXECUTOR, FOMO_EXECUTOR, USER_A, TOKEN, 10**18, "0x3"),
            # a USDG -> ETH conversion carries no token and is not a trade
            leg(FOMO_ENTRY, USER_B, FOMO_EXECUTOR, USDG, 10**6, "0x4"),
            leg(FOMO_EXECUTOR, FOMO_EXECUTOR, USER_B, ETH, 10**15, "0x4")]
    trades = parse_fomo_logs(logs)
    assert [(t.side, t.trader, t.usd) for t in trades] == [("buy", USER_A, None)]


def test_tracker_windows_and_ranking():
    tracker = FomoTracker(max_age=3600)
    trades = parse_fomo_logs(buy(USER_A, 10, "0x1") + buy(USER_B, 20, "0x2") + buy(USER_A, 5, "0x3")
                             + sell(USER_B, 7, "0x4"))
    for i, t in enumerate(trades):
        t.timestamp = 1000 + i
    old = parse_fomo_logs(buy("0x" + "c" * 40, 99, "0x5"))[0]
    old.timestamp = 100
    for t in trades + [old]:
        tracker.add(t)

    stats = tracker.stats(TOKEN, window_sec=600, now=1010)
    assert (stats["buyers"], stats["buys"], stats["sellers"], stats["buy_usd"], stats["sell_usd"]) == (2, 3, 1, 35, 7)
    assert tracker.stats(TOKEN, window_sec=10_000, now=1010)["buyers"] == 3
    assert tracker.top(600, now=1010)[0][0].lower() == TOKEN

    tracker.prune(now=100 + 3601)
    assert tracker.stats(TOKEN, window_sec=10**9, now=5000)["buys"] == 3


def test_fomo_findings():
    assert fomo_findings({"buyers": 9, "sellers": 3, "sells": 4})[0].code == "fomo_sellable"
    assert fomo_findings({"buyers": 9, "sellers": 0, "sells": 0})[0].code == "fomo_no_sells"
    assert fomo_findings({"buyers": 2, "sellers": 0, "sells": 0}) == []
    dump = fomo_findings({"buyers": 10, "sellers": 10, "sells": 11, "buy_usd": 222, "sell_usd": 121_131})
    assert [f.code for f in dump] == ["fomo_sellable", "fomo_dumping"]


def test_weth_legs_are_cash_not_tokens():
    from rhscanner.config import DEFAULT_WETH
    logs = [leg(FOMO_ENTRY, USER_A, FOMO_EXECUTOR, DEFAULT_WETH, 10**15, "0x9"),
            leg(FOMO_EXECUTOR, FOMO_EXECUTOR, FOMO_EXECUTOR, USDG, 3 * 10**6, "0x9")]
    assert parse_fomo_logs(logs) == []
