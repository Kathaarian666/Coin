import asyncio
import time

from rhscanner.bot import ScannerApp
from rhscanner.config import Settings
from test_fomo import TOKEN, buy, parse_fomo_logs


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


async def _watch_app(tmp_path, monkeypatch, now_snapshot, market):
    from rhscanner.exits import Snapshot  # noqa: F401
    app = ScannerApp(Settings(db_path=str(tmp_path / "f.db"), followup_min=15, exit_checks_min=[5, 15],
                              use_dexscreener=False))
    sent = []

    async def fake_broadcast(text):
        sent.append(text)

    async def no_sleep(_):
        return None

    async def fake_current(report, then):
        return now_snapshot, market

    app.broadcast = fake_broadcast
    app.current_snapshot = fake_current
    monkeypatch.setattr("asyncio.sleep", no_sleep)
    return app, sent


REPORT = {"token": "0x" + "1" * 40, "name": "T", "symbol": "T", "score": 80, "findings": [],
          "launch": {"dev_pct": 20.0, "creator": "0xdev"}, "holders": {"top_wallets": {"0xw": 8.0}},
          "market": {"price_usd": "1.0", "liquidity_base": 1000, "liquidity_quote": 10}}


async def test_watch_sends_only_the_follow_up_when_nothing_is_wrong(tmp_path, monkeypatch):
    from rhscanner.exits import Snapshot
    healthy = Snapshot(dev_pct=20.0, top_wallets={"0xw": 8.0}, liquidity_base=900, liquidity_quote=12, price_usd=0.5)
    app, sent = await _watch_app(tmp_path, monkeypatch, healthy, {"price_usd": "0.5", "buys_m5": 10, "sells_m5": 12})
    await app.watch(REPORT)
    assert len(sent) == 1 and "Takip · T" in sent[0] and "sağlıklı geri çekilme" in sent[0]
    await app.rpc.close()


async def test_watch_sends_exit_when_dev_dumps_and_stops(tmp_path, monkeypatch):
    from rhscanner.exits import Snapshot
    dumped = Snapshot(dev_pct=1.0, top_wallets={"0xw": 8.0}, liquidity_base=1100, liquidity_quote=8, price_usd=0.6)
    app, sent = await _watch_app(tmp_path, monkeypatch, dumped, {"price_usd": "0.6"})
    await app.watch(REPORT)
    assert len(sent) == 1 and "ÇIK sinyali" in sent[0] and "Geliştirici satıyor" in sent[0]
    assert app.outcomes.db.execute("SELECT kind FROM signals").fetchall() == [("exit",)]
    await app.rpc.close()


async def test_second_wave_needs_an_old_signal_and_a_quiet_spell(tmp_path):
    app = ScannerApp(Settings(db_path=str(tmp_path / "w.db"), fomo_min_buyers=2, fomo_min_buy_usd=0))
    token = TOKEN.lower()
    calls = []

    async def fake_record(tok, first):
        calls.append((tok, first["kind"]))

    app.record_second_wave = fake_record
    now = time.time()

    def add_buy(user, i, ago):
        [t] = parse_fomo_logs(buy(user, 5, f"0x{i}"))
        t.timestamp = now - ago
        app.tracker.add(t)

    app.check_second_wave(token)
    assert calls == []  # never signalled before
    app.outcomes.record(token, "shadow", ts=now - 1200)
    app.check_second_wave(token)
    assert calls == []  # first signal only 20 minutes ago: same wave
    app.outcomes.db.execute("UPDATE signals SET ts = ?", (now - 7200,))
    for i, user in enumerate(["0x" + c * 40 for c in "abc"]):
        add_buy(user, i, 2400)  # 3 buyers 40 minutes ago: not quiet (bar 2 -> quiet under 1)
    app.check_second_wave(token)
    assert calls == []
    app.tracker.trades.clear()
    app.check_second_wave(token)
    await asyncio.sleep(0)
    assert calls == [(token, "shadow")]
    app.check_second_wave(token)
    await asyncio.sleep(0)
    assert len(calls) == 1  # once per coin
    await app.rpc.close()


async def test_second_wave_is_recorded_with_market_and_v2_momentum(tmp_path):
    app = ScannerApp(Settings(db_path=str(tmp_path / "r.db")))

    class Dex:
        async def token_pairs(self, token):
            return [{"pairAddress": "0xpool", "priceUsd": "3.0", "liquidity": {"usd": 8000}, "fdv": 15000,
                     "txns": {}, "volume": {}, "priceChange": {}, "info": {}}]

    app.analyzer.dexscreener = Dex()
    await app.record_second_wave(TOKEN, {"kind": "alert", "ts": time.time() - 7200, "p0": 1.5})
    [(kind, momentum, features)] = app.outcomes.db.execute("SELECT kind, momentum, features FROM signals").fetchall()
    assert kind == "wave2" and momentum is not None
    assert '"price_vs_first": 2.0' in features and '"first_kind": "alert"' in features and '"fdv": 15000' in features
    await app.rpc.close()
