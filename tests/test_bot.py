import json
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


async def test_paper_test_scores_a_new_coin_at_its_fifth_buyer_and_follows_its_virtual_trade(tmp_path):
    from rhscanner import paper
    from rhscanner.fomo import FomoTrade

    app = ScannerApp(Settings(db_path=str(tmp_path / "r.db"), fomo_min_buyers=99))
    assert app.paper_model is not None
    app.follower.known_since = time.time() - 3 * 86400  # past the learning day
    app.paper_model.bar = 0.0  # every scored coin is a pick in this test

    async def supply(token, fn, out, *a, **k):
        return [10**27]
    app.rpc.try_call_fn = supply
    token = "0x" + "2" * 40
    assert app.paper_model_h is not None  # the second model (+ holder criteria) runs beside it
    app.paper_model_h.bar = 0.0
    asked = []

    async def get_logs(lo, hi, topics, address=None, **k):  # the coin's Transfer logs: 3 holders got coins
        asked.append((lo, hi, address))
        return [{"blockNumber": hex(paper.WARMUP_BLOCKS + 10 + i), "logIndex": "0x0",
                 "topics": [paper.TRANSFER_TOPIC, "0x" + "0" * 64, "0x" + "0" * 24 + w * 40], "data": hex(10**24)}
                for i, w in enumerate("abc")]
    app.rpc.get_logs = get_logs
    t0 = time.time() - 7200

    def trade(who, ts, block, usd=50.0, amount=None, side="buy"):
        return FomoTrade("0x" + who * 64, block, token, side, who * 40, usd, timestamp=ts,
                         amount=amount or int(usd * 1e12))

    await app.on_fomo_trades([FomoTrade("0xaa", 1, "0x" + "3" * 40, "buy", "z" * 40, 5.0, t0 - 9999, 10**12)])
    first = [trade(w, t0 + 10 * i, paper.WARMUP_BLOCKS + 10 + 100 * i) for i, w in enumerate("abcde")]
    for x in first:
        await app.on_fomo_trades([x])
    await asyncio.gather(*list(app.tasks))
    rows = app.paper_log.alerts(0)
    assert len(rows) == 1 and rows[0]["token"] == token and 0 < rows[0]["score"] < 1
    assert asked and asked[0][2] == token and asked[0][1] == paper.WARMUP_BLOCKS + 410  # up to the 5th buyer's block
    h = app.paper_log_h.alerts(0)
    feats = json.loads(app.storage.db.execute("SELECT features FROM paper_log_h").fetchone()[0])
    assert len(h) == 1 and feats["holders"] == 3 and feats["top10_pct"] == 0.3 and "usd_all" in feats
    # price doubles (two buys in a row at 2x the alert price), then the trade runs on
    later = [trade(w, t0 + 600 + i, paper.WARMUP_BLOCKS + 9000 + i, 100.0, amount=int(50e12)) for i, w in enumerate("fg")]
    await app.on_fomo_trades(later)
    app.paper_step(time.time())  # what the bot's minute loop does
    row = app.paper_log.alerts(0)[0]
    # half sold at 2x; the open half is valued at the median of the last 5 prices (1x here): net about +35 %
    assert row["kind"] == "2x" and not row["closed"] and 0.2 < row["ret"] < 0.5
    assert app.paper_log_h.alerts(0)[0]["kind"] == "2x"  # its virtual trade moves on too
    # the 5x rule beside it: no 5x, so at 3 hours it is sold, and worth 0 because the pool's liquidity was pulled
    assert row["kind5"] == "yok" and not row["closed5"]
    later_now = t0 + paper.HOLD5 + 60
    app.paper_step(later_now)
    assert app.paper_log.alerts(0)[0]["kind5"] == "süre" and not app.paper_log.alerts(0)[0]["closed5"]
    checked = []

    async def pulled(token_, t_exit, now):
        checked.append((token_, t_exit))
        return "çekildi"
    app.pool_pulled = pulled
    await app.paper5_step(later_now)
    row = app.paper_log.alerts(0)[0]
    assert row["closed5"] and row["ret5"] == -1.0 and row["chain5"] == "çekildi"
    assert checked == [(token, rows[0]["ts"] + paper.HOLD5)]  # once for both models
    assert app.paper_log_h.alerts(0)[0]["chain5"] == "çekildi"
    await app.rpc.close()


async def test_pool_pulled_reads_the_pools_net_liquidity(tmp_path, monkeypatch):
    from rhscanner import live
    app = ScannerApp(Settings(db_path=str(tmp_path / "p.db")))

    async def head():
        return 1000
    app.rpc.block_number = head
    seen = {}

    async def find_pool(rpc, pm, token, at):
        seen["at"] = at
        return ("0xpool", ()) if token == "0xa" else None

    async def birth(rpc, pm, pool, before):
        return 10

    def liq(block, delta):
        return {"blockNumber": hex(block), "data": "0x" + "00" * 64 + delta.to_bytes(32, "big", signed=True).hex()}
    deltas = {"now": [liq(10, 1000), liq(500, -900)]}

    async def logs(rpc, pm, pool, lo, hi):
        seen["range"] = (lo, hi)
        return deltas["now"]
    monkeypatch.setattr(live, "find_pool", find_pool)
    monkeypatch.setattr(live, "pool_birth", birth)
    monkeypatch.setattr(live, "pool_liquidity_logs", logs)
    now = time.time()
    assert await app.pool_pulled("0xa", now - 10, now) == "çekildi"
    assert seen["at"] == 1000 - 99 and seen["range"] == (10, 901)  # up to the exit's block, from the pool's birth
    deltas["now"] = [liq(10, 1000), liq(500, -500)]
    assert await app.pool_pulled("0xa", now, now) == "var"
    assert await app.pool_pulled("0xb", now, now) == "havuz yok"
    await app.rpc.close()
