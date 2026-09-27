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
    log.record(TOKEN, "shadow", momentum=60, features={"buyers_10m": 6}, ts=T0 + 1800)
    log.record(TOKEN, "filtered", trust=25, momentum=80, features={"findings": ["liq_usd_low"]}, ts=T0 + 3700)
    (sid,) = log.db.execute("SELECT id FROM signals WHERE kind = 'filtered'").fetchone()
    log.db.execute("INSERT INTO samples VALUES (?, 0, ?, 2.0, NULL)", (sid, T0 + 3700))
    gecko = FakeGecko({TOKEN: [1.0, 2.0, 50.0], other: [1.0, 1.5, 1.2]})  # FDV $557k now
    winners, checked = await find_winners(gecko, log, days=3650, min_multiple=10)
    assert checked == 2 and [w["token"] for w in winners] == [TOKEN]
    kinds = [s["kind"] for s in winners[0]["signals"]]
    assert kinds == ["shadow", "filtered"] and winners[0]["signals"][1]["entry_vs_start"] == 2.0

    text = "\n".join(format_winners(3, 10, winners, checked, min_score=20, min_momentum=70, min_buyers=10))
    assert "🚫 Filtreye takıldı (güven 25, momentum 80)" in text and "GÖNDERİLİRDİ" in text
    assert "liq_usd_low" in text and "gölgede 32 dk önce" in text and "başlangıcın 2.0x'i" in text
    assert "Bu sürede" in format_winners(3, 10, [], 0, 30, 70, 10)[0]
