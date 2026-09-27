import sqlite3

from rhscanner.outcomes import CHECKPOINTS_MIN, OutcomeLog, momentum_bucket, summarize

TOKEN = "0x" + "a" * 40
T0 = 1_000_000.0


class FakeDex:
    def __init__(self):
        self.price, self.liq, self.calls = 1.0, 10_000, 0

    async def tokens(self, addresses):
        self.calls += 1
        return [{"baseToken": {"address": a}, "pairAddress": "0xpool", "priceUsd": str(self.price),
                 "liquidity": {"usd": self.liq}} for a in addresses]


async def run_to(log, dex, minute, price, liq=10_000):
    dex.price, dex.liq = price, liq
    return await log.tick(dex, now=T0 + minute * 60)


async def test_samples_follow_checkpoints_and_catch_up_after_downtime():
    log, dex = OutcomeLog(sqlite3.connect(":memory:")), FakeDex()
    assert log.record(TOKEN, "alert", trust=80, momentum=75, ts=T0)
    assert not log.record(TOKEN, "alert", ts=T0)  # one record per token and kind
    assert await run_to(log, dex, 0, 1.0) == 1
    assert await run_to(log, dex, 3, 1.1) == 0  # nothing due before minute 5
    await run_to(log, dex, 5, 1.6)
    await run_to(log, dex, 40, 2.4)  # downtime: one sample, filed under the latest due checkpoint (30)
    await run_to(log, dex, 60, 1.2)
    minutes = [m for (m,) in log.db.execute("SELECT minute FROM samples ORDER BY minute")]
    assert minutes == [0, 5, 30, 60]
    (next_idx,) = log.db.execute("SELECT next_idx FROM signals").fetchone()
    assert CHECKPOINTS_MIN[next_idx] == 90

    [r] = log.results(hours=24, now=T0 + 3600)
    assert (r["max_60"], r["ret_60"], r["rugged"]) == (2.4, 1.2, False)
    s = summarize([r])
    assert s["x2_60"] == 100.0 and s["down50_60"] == 0.0 and s["median_max60"] == 2.4


async def test_rug_detection_and_shadow_momentum():
    log, dex = OutcomeLog(sqlite3.connect(":memory:")), FakeDex()
    log.record(TOKEN, "shadow", features={"buyers_10m": 12}, ts=T0)
    seen = []

    def momentum_fn(features, pairs, pair):
        seen.append((features, len(pairs), pair))
        return 42

    dex.price = 1.0
    await log.tick(dex, momentum_fn, now=T0)
    assert seen == [({"buyers_10m": 12}, 1, "0xpool")]
    assert log.db.execute("SELECT momentum, pair FROM signals").fetchone() == (42, "0xpool")
    await run_to(log, dex, 60, 0.3, liq=1_000)  # liquidity pulled
    [r] = log.results(hours=24, now=T0 + 3600)
    assert r["rugged"] and r["kind"] == "shadow" and momentum_bucket(r["momentum"]) == "🧊 <45"


def test_summary_of_nothing():
    assert summarize([]) == {"n": 0}


async def test_findings_are_returned_and_tabulated():
    from rhscanner.outcomes import finding_table, trust_bucket
    from rhscanner.report import format_findings

    log, dex = OutcomeLog(sqlite3.connect(":memory:")), FakeDex()
    for i in range(6):
        log.record(f"0x{i:040x}", "filtered" if i % 2 else "alert", trust=40 + i * 10,
                   features={"findings": ["DEV_HEAVY", "DEV_HEAVY"] if i < 5 else []}, ts=T0)
    log.record(f"0x{9:040x}", "shadow", features={"findings": ["DEV_HEAVY"]}, ts=T0)
    await run_to(log, dex, 0, 1.0)
    await run_to(log, dex, 60, 2.0)
    results = log.results(hours=24, now=T0 + 3600)
    assert sorted(len(r["findings"]) for r in results) == [0, 1, 2, 2, 2, 2, 2]
    [(code, s)] = finding_table(results)
    assert (code, s["n"], s["x2_60"]) == ("DEV_HEAVY", 5, 100.0)  # shadow ignored, duplicates counted once
    assert finding_table(results, min_n=6) == []
    assert [trust_bucket(t) for t in (None, 29, 30, 50, 70)] == ["?", "⛔ <30", "🔸 30-49", "⚠️ 50-69", "✅ 70+"]
    text = format_findings(72, summarize(results), [(code, s)])
    assert "<code>DEV_HEAVY</code> (5)" in text and "Hepsi</b> (7)" in text
    assert "Veri yok" in format_findings(72, {"n": 0}, [])


async def test_unlisted_coins_are_priced_by_price_fn():
    log = OutcomeLog(sqlite3.connect(":memory:"))

    class NoPairs:
        async def tokens(self, addresses):
            return []

    log.record(TOKEN, "pons", ts=T0)
    prices = {0: 1.0, 60: 3.0}
    await log.tick(NoPairs(), now=T0, price_fn=lambda token: prices[0])
    await log.tick(NoPairs(), now=T0 + 3600, price_fn=lambda token: prices[60])
    [r] = log.results(hours=24, now=T0 + 3600)
    assert (r["kind"], r["max_60"], r["rugged"]) == ("pons", 3.0, False)
