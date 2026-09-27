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
        return 42, {"fdv": 9000}

    dex.price = 1.0
    await log.tick(dex, momentum_fn, now=T0)
    assert seen == [({"buyers_10m": 12}, 1, "0xpool")]
    assert log.db.execute("SELECT momentum, pair FROM signals").fetchone() == (42, "0xpool")
    assert '"fdv": 9000' in log.db.execute("SELECT features FROM signals").fetchone()[0]
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


def test_exit_summary_and_scorecard_splitting():
    from rhscanner.outcomes import summarize_exits
    from rhscanner.report import format_scorecard

    right = {"ret_60": 0.5, "max_60": 1.0, "max_all": 1.0, "rugged": False}
    early = {"ret_60": 1.8, "max_60": 2.1, "max_all": 2.5, "rugged": False}
    s = summarize_exits([right, early])
    assert (s["n"], s["lower_60"], s["down20_60"], s["up50_60"], s["x2_all"]) == (2, 50.0, 50.0, 50.0, 50.0)
    assert summarize_exits([]) == {"n": 0}

    group = summarize([{"max_60": 2.0, "max_all": 2.0, "ret_60": 1.0, "rugged": False}])
    messages = format_scorecard(24, [(f"Grup {i}", group) for i in range(30)], [("🔴 ÇIK", s), ("🟠 DİKKAT", {"n": 0})])
    assert len(messages) > 1 and all(len(m) <= 3500 for m in messages)
    assert messages[0].startswith("📊") and "Grup 29" in messages[-1] and "DİKKAT</b>: veri yok" in messages[-1]
    assert len(format_scorecard(24, [("Tek", group)])) == 1


def test_feature_table_splits_into_thirds():
    from rhscanner.outcomes import feature_table, feature_value
    from rhscanner.report import format_analysis

    def result(buyers, smart, x2):
        return {"kind": "alert", "trust": 60, "momentum": 70, "max_60": 2.0 if x2 else 1.0, "max_all": 1.0,
                "ret_60": 1.0, "rugged": False,
                "features": {"buyers_10m": buyers, "buy_usd_10m": buyers * 20.0, "smart_buyers_10m": smart,
                             "buyers_5m": 4, "buyers_prev_5m": 0}}

    results = [result(b, 0 if b < 40 else 2, b >= 40) for b in range(10, 70)]
    assert feature_value(results[0], "avg_buy_usd") == 20.0 and feature_value(results[0], "accel_5m") == 4.0
    table = dict(feature_table(results))
    thirds = table["10 dk alıcı"]
    assert [t for t, _ in thirds] == ["10–29", "30–49", "50–69"]
    assert [s["x2_60"] for _, s in thirds] == [0.0, 50.0, 100.0]
    assert [t for t, _ in table["akıllı cüzdan sayısı"]] == ["0", "2"]  # two values: two parts
    assert "güven skoru" not in table  # one value only: nothing to split
    messages = format_analysis(168, len(results), list(table.items()))
    assert "10 dk alıcı" in messages[0] and all(len(m) <= 3500 for m in messages)


def test_backtest_compares_v1_and_v2_selection():
    from rhscanner.outcomes import backtest, momentum_v2_of
    from rhscanner.report import format_backtest

    def sig(ts, momentum, fdv, won):
        return {"ts": ts, "trust": 60, "momentum": momentum, "max_60": 3.0 if won else 1.0, "max_all": 1.0,
                "ret_60": 1.0, "rugged": False, "features": {"fdv": fdv, "age_min": 100}}

    # small coins sit just under the bar in v1 and win; big ones pass v1 and lose
    results = [sig(i, 62, 10_000, True) for i in range(10)] + [sig(i, 75, 5_000_000, False) for i in range(10)]
    # v1 gave a 100-minute-old coin +3; v2 drops that and adds the FDV points
    assert momentum_v2_of(results[0]) == 62 - 3 + 15 and momentum_v2_of(results[-1]) == 75 - 3 - 10
    assert momentum_v2_of({"momentum": 50, "features": {"momentum_v2": 80}}) == 80  # recorded live
    halves = dict(backtest(results, min_score=30, min_momentum=70))
    assert halves["Tümü"]["v1"]["x2_60"] == 0.0 and halves["Tümü"]["v2"]["x2_60"] == 100.0
    assert halves["Tümü"]["added"]["n"] == 10 and halves["Tümü"]["dropped"]["n"] == 10
    text = "\n".join(format_backtest(168, 30, 70, list(halves.items()), v2_on=False))
    assert "Yeni yarı" in text and "sadece v2 ekler (10)" in text and "Şu an kullanılan: v1" in text


async def test_unmeasured_signals_are_counted_and_shown():
    from rhscanner.report import format_scorecard

    log = OutcomeLog(sqlite3.connect(":memory:"))
    log.record(TOKEN, "alert", ts=T0)
    log.record("0x" + "c" * 40, "alert", ts=T0)
    dex = FakeDex()

    class Partial(FakeDex):
        async def tokens(self, addresses):
            return [p for p in await super().tokens(addresses) if p["baseToken"]["address"] == TOKEN]

    await log.tick(Partial(), now=T0)  # only one of the two is listed yet
    assert log.unmeasured(24, now=T0 + 3600) == {"alert": 1}
    await log.tick(dex, now=T0 + 3600, price_fn=None)
    text = format_scorecard(24, [], None, {"alert": 1, "pons": 5})[0]
    assert "ölçülemeyen: bildirim 1" in text and "pons" not in text


def test_lower_bar_candidates_pick_small_shadows():
    from rhscanner.outcomes import lower_bar_candidates

    def shadow(buyers, fdv, momentum):
        return {"momentum": momentum, "max_60": 2.0, "max_all": 2.0, "ret_60": 1.0, "rugged": False,
                "features": {"buyers_10m": buyers, "fdv": fdv, "momentum_v2": momentum}}

    picked = lower_bar_candidates([shadow(8, 9000, 80), shadow(7, 9000, 80), shadow(9, 50_000, 80),
                                   shadow(9, None, 80), shadow(9, 9000, 60)], min_buyers=10, min_momentum=70)
    assert picked["n"] == 1


def test_blocking_gates_name_the_bar_and_value():
    from rhscanner.outcomes import blocking_gates
    signal = {"trust": 25, "momentum": 60, "features": {"buyers_10m": 8, "buy_usd_10m": 300, "momentum_v2": 64}}
    assert blocking_gates(signal, 30, 70, 10, 500) == [
        "alıcı 8 (eşik 10)", "10 dk alım $300 (eşik $500)", "güven 25 (eşik 30)", "momentum 64 (eşik 70)"]
    assert blocking_gates(signal, 20, 60, 8, 300) == []
    risky = {**signal, "features": {**signal["features"], "rug_risk": 70}}
    assert blocking_gates(risky, 20, 60, 8, 300, max_rug=60) == ["rug riski 70 (sınır 60)"]


def test_parameter_sweep_trades_precision_for_recall():
    from rhscanner.outcomes import parameter_sweep
    from rhscanner.report import format_sweep

    def sig(momentum, trust, big):
        return {"trust": trust, "momentum": momentum, "max_60": 1.0, "max_all": 6.0 if big else 1.0,
                "ret_60": 1.0, "rugged": False, "features": {"momentum_v2": momentum}}

    results = [sig(90, 60, True) for _ in range(10)] + [sig(65, 60, True) for _ in range(5)] + \
              [sig(65, 10, False) for _ in range(20)]
    rows = {(r["min_momentum"], r["min_score"]): r for r in parameter_sweep(results, min_n=5)}
    assert rows[(85, 0)]["x5_all"] == 100.0 and rows[(85, 0)]["recall"] == 66.7
    assert rows[(60, 20)]["recall"] == 100.0 and rows[(60, 0)]["x5_all"] == 42.9
    text = "\\n".join(format_sweep(168, 35, 15, list(rows.values()), (70, 30)))
    assert "<b>60 / 20</b>" in text and "yakalanan %100.0" in text and "yakalanan %66.7" in text
