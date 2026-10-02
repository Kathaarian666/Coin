import asyncio
import time

from rhscanner.bot import ScannerApp
from rhscanner.config import Settings
from test_fomo import buy, parse_fomo_logs


async def test_alerts_once_per_token_and_not_during_warmup(tmp_path):
    app = ScannerApp(Settings(db_path=str(tmp_path / "b.db"), fomo_min_buyers=2, fomo_min_buy_usd=0))
    users = ["0x" + c * 40 for c in "abcd"]

    async def feed(user_ids, warmup):
        trades = parse_fomo_logs([leg for i, u in user_ids for leg in buy(u, 5, f"0x{i}")])
        for t in trades:
            t.timestamp = time.time()
            app.tracker.add(t)
        await app.on_fomo_trades(trades, warmup)

    await feed([(0, users[0])], warmup=False)
    assert app.queue.qsize() == 0  # one buyer is below the threshold
    await feed([(1, users[1])], warmup=False)
    assert app.queue.qsize() == 1 and app.queue.get_nowait().from_fomo
    await feed([(2, users[2])], warmup=False)
    assert app.queue.qsize() == 0  # already alerted

    await app.rpc.close()
    app = ScannerApp(Settings(db_path=str(tmp_path / "c.db"), fomo_min_buyers=2, fomo_min_buy_usd=0))
    await feed([(3, users[0]), (4, users[1])], warmup=True)
    assert app.queue.qsize() == 0  # trending before startup: no alert
    await app.rpc.close()


async def test_small_volume_does_not_alert(tmp_path):
    app = ScannerApp(Settings(db_path=str(tmp_path / "v.db"), fomo_min_buyers=2, fomo_min_buy_usd=500))
    trades = parse_fomo_logs([leg for i, u in enumerate(["0x" + "a" * 40, "0x" + "b" * 40])
                              for leg in buy(u, 5, f"0x{i}")])
    for t in trades:
        t.timestamp = time.time()
        app.tracker.add(t)
    await app.on_fomo_trades(trades)
    assert app.queue.qsize() == 0  # 2 buyers but only $10 bought
    await app.rpc.close()


async def test_record_mode_scores_a_new_coin_at_its_third_buyer_and_reads_its_hour(tmp_path):
    from rhscanner.fomo import FomoTrade
    from rhscanner.scan import DELAY, HOLD, WARMUP_BLOCKS

    app = ScannerApp(Settings(db_path=str(tmp_path / "r.db"), fomo_min_buyers=99))
    assert app.scan_model is not None
    app.scanner.known_since = time.time() - 3 * 86400  # past the learning day

    async def supply(token, fn, out, *a, **k):
        return [10**27]
    app.rpc.try_call_fn = supply
    token = "0x" + "2" * 40
    t0 = time.time() - DELAY - HOLD - 120

    def trade(who, ts, block, usd=50.0, side="buy"):
        return FomoTrade("0x" + who * 64, block, token, side, who * 40, usd, timestamp=ts, amount=int(usd * 1e12))

    await app.on_fomo_trades([FomoTrade("0xaa", 1, "0x" + "3" * 40, "buy", "z" * 40, 5.0, t0 - 9999, 10**12)])
    first = [trade(w, t0 + i, WARMUP_BLOCKS + 10 + i) for i, w in enumerate("abc")]
    await app.on_fomo_trades(first)
    await asyncio.gather(*list(app.tasks))
    rows = app.scan_log.rows(0)
    assert len(rows) == 1 and rows[0]["token"] == token and 0 < rows[0]["score"] < 1 and not rows[0]["done"]
    later = [trade(w, t0 + DELAY + HOLD - 100 + i, WARMUP_BLOCKS + 5000 + i, 120.0) for i, w in enumerate("defg")]
    await app.on_fomo_trades(later)
    app.measure_due(time.time())  # what the bot's minute loop does
    row = app.scan_log.rows(0)[0]
    assert row["done"] and row["result"] is not None and row["high"] > 0
    assert -30 < row["result"] < 0  # flat price: the round trip costs fee and slippage
    await app.rpc.close()
