"""Paper test rules (rhscanner/paper.py) against the research definitions (scripts/trade_sim.py)."""

import math
import sqlite3

from rhscanner import paper
from rhscanner.paper import Book, Follower, Trade


def buy(ts, price, who="w", usd=10.0, block=None):
    return Trade(ts, block or int(ts * 10), 1, who, usd, int(usd / price))


def sell(ts, price, who="s", usd=10.0):
    return Trade(ts, int(ts * 10), 0, who, usd, int(usd / price))


def test_half_is_sold_at_2x_and_the_rest_on_the_trailing_rule():
    p = 1e-6
    trades = [buy(0, p), buy(100, 2.1 * p), buy(101, 2.2 * p), buy(200, 8 * p), buy(201, 8 * p),
              sell(300, 3.9 * p), sell(301, 3.8 * p)]
    t = paper.paper_trade(trades, 0, 1000)
    assert t["kind"] == "2x" and t["open"] == 0
    assert t["legs"][0][1:] == (0.5, 2 * p)
    assert t["legs"][1][0] == 301 and abs(t["legs"][1][2] / (3.8 * p) - 1) < 1e-5  # under half the 8x peak, twice


def test_stop_before_2x_sells_everything_and_needs_two_trades():
    p = 1e-6
    lone = [buy(0, p), sell(40, 0.4 * p), buy(41, 1.0 * p)]
    assert paper.paper_trade(lone, 0, 1000)["kind"] == "yok"  # one bad print is not a stop
    two = lone + [sell(50, 0.45 * p), sell(51, 0.4 * p), buy(60, 3 * p), buy(61, 3 * p)]
    t = paper.paper_trade(two, 0, 1000)
    assert t["kind"] == "stop" and t["open"] == 0 and t["legs"][0][1] == 1.0


def test_entry_waits_30_seconds_and_takes_the_price_then():
    p = 1e-6
    trades = [buy(0, p), buy(20, 1.5 * p)]
    assert paper.paper_trade(trades, 0, 10) is None
    t = paper.paper_trade(trades, 0, 100)
    assert abs(t["p_alert"] / p - 1) < 1e-5 and abs(t["p_in"] / (1.5 * p) - 1) < 1e-5


def test_net_return_charges_the_minimum_fee_both_ways():
    t = {"p_in": 1.0, "legs": [(1, 1.0, 1.0)], "open": 0.0}
    r = paper.net_return(t, 1e12, 20.0)
    assert abs(r - (19.05 - 0.95 - 20) / 20) < 1e-6  # $0.95 in, $0.95 out (0.5 % of $19 is less)


def test_follower_reports_the_fifth_distinct_buyer_of_a_new_coin_only():
    f = Follower(known={"0xold"}, known_since=-1e9, learn=0)
    f.start_block = 0
    base = paper.WARMUP_BLOCKS + 1
    assert f.add("0xold", Trade(1, base, 1, "a", 1, 1)) is None  # traded before the bot: not new
    got = [f.add("0xnew", Trade(i, base + i, 1, w, 1, 1)) for i, w in enumerate("aabcde")]
    assert got == [None, None, None, None, None, 5]


def test_book_rate_and_settle():
    db = sqlite3.connect(":memory:")
    book = Book(db, seed="/nonexistent")
    assert math.isnan(book.rate(["x"]))
    f = Follower(learn=0)
    f.coins["0xc"] = paper.Coin(0, True, trades=[buy(10, 2e-6), buy(11, 2.1e-6)])
    f.coins["0xd"] = paper.Coin(0, True, trades=[buy(10, 1.1e-6), buy(11, 1.2e-6)])
    f.coins["0xe"] = paper.Coin(0, True, trades=[buy(10, 3e-6), buy(5000, 3e-6)])  # 2x only after the hour
    for coin in ("0xc", "0xd", "0xe", "0xgone"):  # a coin the bot lost (restart) adds nothing
        book.watch(coin, 0, 1e-6, ["x", "y"])
    book.settle(f, 4000)
    assert db.execute("SELECT n, hits FROM paper_book WHERE wallet = 'x'").fetchone() == (3, 1)
    assert abs(book.rate(["x", "y"]) - 2 / 6) < 1e-9
    assert db.execute("SELECT COUNT(*) FROM paper_pending").fetchone()[0] == 0
