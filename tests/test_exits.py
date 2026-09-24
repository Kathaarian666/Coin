from rhscanner.exits import STRONG, WARNING, Snapshot, breakeven_multiple, evaluate_exit, exit_level

THEN = Snapshot(dev_pct=12.0, top_wallets={"0xa": 6.0, "0xb": 2.0}, liquidity_base=1_000_000,
                liquidity_quote=50.0, price_usd=1.0)
QUIET = {"buyers": 5, "sellers": 1, "buy_usd": 400, "sell_usd": 50}


def snap(**kw):
    base = dict(dev_pct=12.0, top_wallets={"0xa": 6.0, "0xb": 2.0}, liquidity_base=1_000_000,
                liquidity_quote=50.0, price_usd=0.4)
    base.update(kw)
    return Snapshot(**base)


def test_price_drop_alone_is_not_an_exit():
    assert evaluate_exit(THEN, snap(price_usd=0.3), QUIET, {"buys": 20, "sells": 25}) == []


def test_dev_and_whale_dumps_are_strong():
    reasons = evaluate_exit(THEN, snap(dev_pct=2.0, top_wallets={"0xa": 1.0, "0xb": 0.0}), QUIET, {})
    assert [lvl for lvl, _ in reasons] == [STRONG, STRONG]  # 0xb held <3%, so its exit is not flagged
    assert exit_level(reasons) == STRONG


def test_buys_shrinking_the_token_side_are_not_a_liquidity_pull():
    # a buying spree removes tokens but adds quote: not a withdrawal
    assert evaluate_exit(THEN, snap(liquidity_base=400_000, liquidity_quote=120.0), QUIET, {}) == []
    reasons = evaluate_exit(THEN, snap(liquidity_base=300_000, liquidity_quote=15.0), QUIET, {})
    assert reasons and reasons[0][0] == STRONG and "Likidite çekiliyor" in reasons[0][1]


def test_flow_reversal_and_sell_wave_are_warnings():
    fomo = {"buyers": 0, "sellers": 4, "buy_usd": 0, "sell_usd": 300}
    reasons = evaluate_exit(THEN, snap(), fomo, {"buys": 4, "sells": 20})
    assert [lvl for lvl, _ in reasons] == [WARNING, WARNING] and exit_level(reasons) == WARNING


def test_breakeven_multiple():
    assert breakeven_multiple(3) == 1.93
    assert breakeven_multiple(5) == 1.47
    assert breakeven_multiple(10) == 1.21
    assert breakeven_multiple(0.9) is None  # the minimum fee eats the whole position
