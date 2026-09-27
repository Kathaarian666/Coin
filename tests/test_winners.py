import sqlite3

from rhscanner.outcomes import OutcomeLog
from rhscanner.report import format_winners
from rhscanner.winners import entry_of, find_winners, parse_pool, run_of

T0 = 1_790_000_000.0
TOKEN = "0x" + "a" * 40


def pool_item(token, created="2026-09-26T17:53:59Z", volume=1e6):
    return {"attributes": {"address": "0xpool" + token[-4:], "name": "HOODS / USDG", "pool_created_at": created,
                           "volume_usd": {"h24": str(volume)}, "fdv_usd": "557034.2"},
            "relationships": {"base_token": {"data": {"id": "robinhood_" + token}}}}


def candles(prices):
    return [[T0 + i * 3600, p, p * 1.1, p * 0.9, p, 1000] for i, p in enumerate(prices)]


def test_parse_pool_and_run():
    pool = parse_pool(pool_item(TOKEN))
    assert pool["token"] == TOKEN and pool["symbol"] == "HOODS" and pool["created"] == 1790445239.0
    series = candles([1.0, 2.0, 50.0, 20.0])
    series[0][5] = 10  # a dust hour is skipped
    run = run_of(series, fdv_now=100_000)
    assert run["multiple"] == 25 and run["hours_to_peak"] == 1 and run["peak_fdv"] == 250_000
    entry = entry_of(series, run, T0 + 3700, 4.0)
    assert entry["entry_vs_start"] == 2.0 and entry["peak_after"] == 12.5 and entry["before_peak"]


class FakeGecko:
    def __init__(self, series):
        self.series = series

    async def pools(self):
        return [parse_pool(pool_item(t)) for t in self.series]

    async def hourly(self, pool):
        return next(candles(p) for t, p in self.series.items() if pool == "0xpool" + t[-4:])


async def test_winners_are_matched_with_signals():
    log = OutcomeLog(sqlite3.connect(":memory:"))
    other = "0x" + "b" * 40
    log.record(TOKEN, "shadow", momentum=60, features={"buyers_10m": 6, "buy_usd_10m": 200}, ts=T0 + 1800)
    log.record(TOKEN, "filtered", trust=25, momentum=80,
               features={"findings": ["liq_usd_low"], "buyers_10m": 12, "buy_usd_10m": 900, "momentum_v2": 80},
               ts=T0 + 3700)
    (sid,) = log.db.execute("SELECT id FROM signals WHERE kind = 'filtered'").fetchone()
    log.db.execute("INSERT INTO samples VALUES (?, 0, ?, 2.0, NULL)", (sid, T0 + 3700))
    gecko = FakeGecko({TOKEN: [1.0, 2.0, 50.0], other: [1.0, 1.5, 1.2]})  # FDV $557k now
    winners, checked, candidates = await find_winners(gecko, log, days=3650, min_multiple=10)
    assert candidates == 2
    assert (await find_winners(gecko, log, days=3650, min_multiple=10, budget_sec=-1))[1:] == (0, 2)
    assert checked == 2 and [w["token"] for w in winners] == [TOKEN]
    kinds = [s["kind"] for s in winners[0]["signals"]]
    assert kinds == ["shadow", "filtered"] and winners[0]["signals"][1]["entry_vs_start"] == 2.0

    bars = {"min_score": 20, "min_momentum": 70, "min_buyers": 10, "min_buy_usd": 500}
    text = "\n".join(format_winners(7, 10, winners, checked, bars))
    assert "🚫 Filtreye takıldı (alıcı 12, güven 25, momentum 80)" in text and "eşiklerin hepsini geçiyor" in text
    assert "yakalanırdı: 1/1" in text and "erken (başlangıcın ≤2x'inde): 1" in text
    assert "liq_usd_low" in text and "gölgede 32 dk önce" in text and "başlangıcın 2.0x'i" in text
    strict = "\n".join(format_winners(7, 10, winners, checked, {**bars, "min_score": 30}))
    assert "bugün engelleyen: güven 25 (eşik 30)" in strict and "yakalanırdı: 0/1" in strict
    assert "Bu sürede" in format_winners(7, 10, [], 0, bars)[0]
    assert "40 adaydan 12'i tarandı" in format_winners(7, 10, [], 12, bars, 40)[0]
