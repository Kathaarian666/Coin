import sqlite3

from rhscanner.fomo import FomoTrade, FomoTracker
from rhscanner.wallets import WalletBook

NOW = 1_000_000.0


def t(side, wallet, token, usd, amount, ago=3600):
    return FomoTrade("0x", 1, token, side, wallet, usd, NOW - ago, amount)


def test_smart_wallets_need_enough_winning_round_trips():
    book = WalletBook(sqlite3.connect(":memory:"))
    trades = []
    for i in range(6):  # 'good': 5 wins out of 6, profitable
        token = f"0x{i:040x}"
        trades += [t("buy", "good", token, 20, 1000), t("sell", "good", token, 60 if i < 5 else 5, 1000)]
    for i in range(6):  # 'bad': loses every time
        token = f"0x{i + 100:040x}"
        trades += [t("buy", "bad", token, 20, 1000), t("sell", "bad", token, 10, 1000)]
    trades += [t("buy", "eth", "0x" + "e" * 40, None, 1000)]  # no USD value: ignored
    book.add(trades)
    book.refresh(now=NOW)
    assert set(book.smart) == {"good"}
    good = book.smart["good"]
    assert (good.closed, good.wins, round(good.pnl_usd)) == (6, 5, 185)  # 5 x (+40) and one -15

    tracker = FomoTracker()
    token = "0x" + "a" * 40
    tracker.add(FomoTrade("0x", 1, token, "buy", "good", 10, NOW - 60, 5))
    tracker.add(FomoTrade("0x", 1, token, "buy", "bad", 10, NOW - 60, 5))
    assert [s.wallet for s in book.smart_buyers(tracker, token, now=NOW)] == ["good"]


def test_partial_sells_are_costed_proportionally_and_old_positions_pruned():
    book = WalletBook(sqlite3.connect(":memory:"))
    token = "0x" + "b" * 40
    book.add([t("buy", "w", token, 100, 1000), t("sell", "w", token, 80, 500)])  # sold half for 80: +30
    [s] = book.stats(now=NOW)
    assert (s.closed, s.wins, round(s.pnl_usd)) == (1, 1, 30)
    book.refresh(now=NOW + 8 * 86400)
    assert book.db.execute("SELECT COUNT(*) FROM fomo_positions").fetchone() == (0,)


def test_huge_raw_amounts_are_stored():
    book = WalletBook(sqlite3.connect(":memory:"))
    book.add([t("buy", "w", "0x" + "c" * 40, 10, 10**30)])
    assert book.db.execute("SELECT buy_amount FROM fomo_positions").fetchone()[0] == 1e30
