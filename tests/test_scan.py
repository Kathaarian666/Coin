import math

from rhscanner.scan import (DELAY, HOLD, WARMUP_BLOCKS, ScanLog, ScanModel, Scanner, Trade, checkpoint_features,
                            evaluate, money_back, summary)


def buy(ts, who, usd=50.0, price=1e-12, block=None):
    return Trade(ts, block or WARMUP_BLOCKS + 100 + int(ts), 1, who, usd, int(usd / price))


def test_checkpoint_is_the_third_distinct_buyer_of_a_coin_seen_from_birth():
    sc = Scanner(learn=0)
    assert sc.add("0xOld", Trade(0, 1, 1, "a", 10, 10**12)) is None  # sets the start block; inside the warm-up
    for who in "bcd":
        assert sc.add("0xold", Trade(1, 2, 1, who, 10, 10**12)) is None  # old coin: never checkpointed
    assert sc.add("0xNew", buy(10, "a")) is None
    assert sc.add("0xNew", buy(11, "a")) is None  # the same buyer again
    assert sc.add("0xNew", buy(12, "b")) is None
    assert sc.add("0xNew", buy(13, "c")) == 3  # trade index of the 3rd distinct buyer
    assert sc.add("0xNew", buy(14, "d")) is None  # only once
    assert not sc.coins["0xold"].trades  # nothing is kept for coins seen mid-life


def test_features_follow_the_research_definitions():
    trades = [buy(0, "a", 100, 1e-12), buy(60, "b", 50, 2e-12), Trade(90, WARMUP_BLOCKS + 190, 0, "a", 30, 10**12),
              buy(120, "c", 150, 3e-12)]
    f = checkpoint_features(trades, 3, 3, 1e21, (WARMUP_BLOCKS + 100 - 1192, 4))
    assert f["mins_to_k"] == 2 and f["trades_to_k"] == 4
    assert f["usd_all"] == 300 and f["max_buy"] == 150 and f["usd_per_trade"] == 100
    assert f["top_buyer_share"] == 0.5 and f["sellers"] == 1 and math.isclose(f["early_sold"], 1 / 3)
    assert math.isclose(f["sell_usd_share"], 30 / 330)
    assert math.isclose(f["runup"], 2.0)  # median of the 3 buy prices / the first
    assert math.isclose(f["fdv"], 2e-12 * 1e21)
    assert f["is_pons"] == 1.0 and f["launcher_prior"] == 4 and 2 < f["launch_age_min"] < 3


def test_json_model_scores_like_a_tree_ensemble():
    # one stump: feature 0 <= 10 -> -1, else +1 (missing goes left); baseline 0
    tree = [[0, 10.0, True, 1, 2, False, 0.0], [0, 0, False, 0, 0, True, -1.0], [0, 0, False, 0, 0, True, 1.0]]
    m = ScanModel({"features": ["usd_all"], "baseline": 0.0, "trees": [tree], "bar10": 0.5, "bar20": 0.4})
    assert math.isclose(m.score({"usd_all": 5}), 1 / (1 + math.e))
    assert math.isclose(m.score({"usd_all": 50}), 1 / (1 + math.exp(-1)))
    assert m.score({"usd_all": math.nan}) == m.score({"usd_all": 5})


def test_shipped_model_loads_and_scores():
    m = ScanModel.load()
    assert m is not None and len(m.trees) > 10
    s = m.score({f: 1.0 for f in m.features})
    assert 0 < s < 1 and 0 < m.bar20 <= m.bar10 < 1


def test_hour_result_pays_a_doubling_and_costs_a_flat_hour():
    base = [buy(0, "a"), buy(10, "b"), buy(20, "c")]
    up = base + [buy(DELAY + 600 + i, f"x{i}", 50, 2.5e-12) for i in range(5)] + \
        [buy(DELAY + HOLD - 60 + i, f"y{i}", 50, 2.5e-12) for i in range(3)]
    depth, p_in, result, high = evaluate(up, 20)
    assert p_in > 1e-12 and high > 2 and result > 80
    flat = evaluate(base, 20)
    assert -25 < flat[2] < 0  # no trade after the entry: the round trip costs fee and slippage
    assert math.isclose(money_back(1.0, 1e9), 100 - 0.95 - 0.95, rel_tol=1e-3)


def test_record_rows_and_summary(tmp_path):
    import sqlite3
    log = ScanLog(sqlite3.connect(str(tmp_path / "s.db")))
    for i, (score, result) in enumerate([(0.9, 120.0), (0.5, -10.0), (0.1, None)]):
        log.add(f"0x{i}", 1000.0 + i, score, 0.8, 0.4, {"usd_all": 1.0, "fdv": math.nan})
        if result is not None:
            log.close(f"0x{i}", 5000, 1e-12, result, 2.0)
    assert [t for t, _ in log.due(10**9)] == ["0x2"]
    s = summary(log.rows(0))
    assert s["scored"] == 3 and s["measured"] == 2 and s["pending"] == 1
    assert s["top10"]["n"] == 1 and s["top10"]["mean"] == 120 and s["top20"]["n"] == 2 and s["top20"]["win"] == 0.5


def test_known_coins_and_the_learning_day_are_not_scored():
    seen = []
    sc = Scanner(known={"0xold"}, known_since=0, on_new=lambda t, ts: seen.append(t))
    sc.add("0xFirst", Trade(86400, 1, 1, "a", 10, 10**12))  # sets the start block
    for i, who in enumerate("abc"):  # traded on Fomo before (kept in the database): never new
        assert sc.add("0xOld", buy(86400 + i, who)) is None
    for i, who in enumerate("abc"):
        r = sc.add("0xNew", buy(86400 + 10 + i, who))
    assert r == 2 and seen == ["0xfirst", "0xnew"]
    fresh = Scanner(known_since=1000.0)  # a fresh install: first day only learns which coins exist
    fresh.add("0xFirst", Trade(1000, 1, 1, "a", 10, 10**12))
    assert all(fresh.add("0xNew2", buy(2000 + i, w)) is None for i, w in enumerate("abc"))
