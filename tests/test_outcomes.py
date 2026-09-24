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
