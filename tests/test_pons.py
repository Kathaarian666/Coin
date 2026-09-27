import sqlite3
import time

from rhscanner.bot import ScannerApp
from rhscanner.config import Settings
from rhscanner.launches import LaunchIndex
from rhscanner.pons import CURVE_BUY, CURVE_SELL, PonsTracker, junk_reasons, parse_curve_logs

CURVE = "0x" + "c" * 40
TOKEN = "0x" + "7" * 40
DEV = "0x" + "d" * 40
ROUTER = "0x" + "e" * 40
LAUNCH_BLOCK = 1_000


def topic(address: str) -> str:
    return "0x" + address[2:].rjust(64, "0")


def curve_log(kind: str, trader: str, eth: float, tokens: float, block: int, curve: str = CURVE) -> dict:
    first, second = (eth, tokens) if kind == CURVE_BUY else (tokens, eth)
    words = [int(first * 1e18), int(second * 1e18), 0, 0]
    return {"address": curve, "topics": [kind, topic(ROUTER), topic(trader)],
            "data": "0x" + "".join(f"{w:064x}" for w in words), "blockNumber": hex(block)}


def launch_log(token: str, curve: str, launcher: str, block: int) -> dict:
    return {"topics": ["0x8d4aad", topic(token), topic(curve), topic(launcher)], "blockNumber": hex(block)}


def test_parse_buys_and_sells():
    buy, sell = parse_curve_logs([curve_log(CURVE_BUY, DEV, 0.5, 1000, 5), curve_log(CURVE_SELL, DEV, 0.2, 400, 6),
                                  {"topics": ["0xother"], "data": "0x", "address": CURVE, "blockNumber": "0x1"}])
    assert (buy.side, buy.trader, buy.eth, buy.tokens, buy.block) == ("buy", DEV, 0.5, 1000, 5)
    assert (sell.side, sell.eth, sell.tokens) == ("sell", 0.2, 400)


def test_stats_and_junk_reasons():
    tracker = PonsTracker()
    now = time.time()
    logs = [curve_log(CURVE_BUY, DEV, 1.0, 1000, LAUNCH_BLOCK)]  # the dev's own buy at launch
    logs += [curve_log(CURVE_BUY, f"0x{i:040x}", 0.1, 50, LAUNCH_BLOCK + 100 + i) for i in range(1, 9)]
    for trade in parse_curve_logs(logs):
        trade.timestamp = now
        tracker.add(trade)
    stats = tracker.stats(CURVE, DEV, LAUNCH_BLOCK, 600, now)
    assert stats["buyers_10m"] == 8 and stats["buyers"] == 8  # the dev does not count as a buyer
    assert stats["dev_buy_share"] == 0.556 and stats["early_share"] == 0 and not stats["dev_sold"]
    assert tracker.price(CURVE) == 0.1 / 50
    assert junk_reasons(stats, launches_24h=1) == ["dev_alimi"]
    assert "seri_dev" in junk_reasons(stats, launches_24h=25)

    whale = {**stats, "dev_buy_share": 0.0, "top_buyer_share": 0.7, "dev_sold": True,
             "sell_eth": stats["buy_eth"], "buys": 40}
    assert junk_reasons(whale, 0) == ["dev_satti", "tek_alici", "satis_baskisi", "tekrar_alim"]


def test_launch_index_keeps_curves_and_migrates_old_tables():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE pons_launches (token TEXT PRIMARY KEY, launcher TEXT NOT NULL, block INTEGER NOT NULL)")
    index = LaunchIndex(db)
    index._store([launch_log(TOKEN, CURVE, DEV, 10), launch_log("0x" + "8" * 40, "0x" + "9" * 40, DEV, 20)])
    assert index.by_curve(CURVE.upper().replace("0X", "0x")) == (TOKEN, DEV, 10)
    assert index.curve_of(TOKEN) == CURVE
    assert index.launches_since(DEV, 15) == 1 and index.launches_since(DEV, 0) == 2


async def test_pons_signals_are_recorded_once_with_junk_reasons(tmp_path):
    app = ScannerApp(Settings(db_path=str(tmp_path / "p.db"), pons_min_buyers=5, pons_min_buy_usd=100,
                              pons_early_min_buyers=2, pons_early_min_buy_usd=50))
    app.eth_usd = 3000.0
    app.analyzer.launches._store([launch_log(TOKEN, CURVE, DEV, LAUNCH_BLOCK)])

    async def feed(buyers, block, warmup=False):
        trades = parse_curve_logs([curve_log(CURVE_BUY, b, 0.02, 10, block) for b in buyers])
        for t in trades:
            t.timestamp = time.time()
            app.pons.add(t)
        await app.on_pons_trades(trades, warmup)

    wallets = [f"0x{i:040x}" for i in range(1, 6)]
    kinds = lambda: [k for (k,) in app.outcomes.db.execute("SELECT kind FROM signals ORDER BY id")]  # noqa: E731
    await feed(wallets[:1], LAUNCH_BLOCK + 500)
    assert kinds() == []  # 1 buyer: too few for either bar
    await feed(wallets[1:2], LAUNCH_BLOCK + 600, warmup=True)
    assert kinds() == []  # warmup never signals
    await feed(wallets[2:3], LAUNCH_BLOCK + 650)
    assert kinds() == ["pons_early"]  # 3 buyers, $180: the early bar only
    await feed(wallets[3:], LAUNCH_BLOCK + 800)
    rows = app.outcomes.db.execute("SELECT token, kind, features FROM signals ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(TOKEN, "pons_early"), (TOKEN, "pons")]
    assert '"buyers_10m": 5' in rows[1][2] and '"findings": []' in rows[1][2]
    await feed(["0x" + "f" * 40], LAUNCH_BLOCK + 900)
    assert len(kinds()) == 2  # once per coin and bar
    assert app.pons_price(TOKEN) == 0.002 * 3000.0
    await app.rpc.close()


async def test_old_coins_are_not_signalled(tmp_path):
    app = ScannerApp(Settings(db_path=str(tmp_path / "o.db"), pons_min_buyers=1, pons_min_buy_usd=0,
                              pons_max_age_min=60))
    app.eth_usd = 3000.0
    app.analyzer.launches._store([launch_log(TOKEN, CURVE, DEV, LAUNCH_BLOCK)])
    trades = parse_curve_logs([curve_log(CURVE_BUY, "0x" + "1" * 40, 1.0, 10, LAUNCH_BLOCK + 61 * 600)])
    for t in trades:
        t.timestamp = time.time()
        app.pons.add(t)
    await app.on_pons_trades(trades)
    assert app.outcomes.db.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0
    await app.rpc.close()
