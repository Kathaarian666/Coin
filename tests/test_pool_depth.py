"""scripts/pool_depth.py maths: V4 virtual reserves, the curve fit, and scorecard.net with measured depths."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pool_depth as pd_  # noqa: E402
import scorecard  # noqa: E402

Q96 = 2 ** 96


def test_v4_reserve_matches_constant_product():
    # price 4 quote per token (currency1 per currency0): sqrtP = 2; L = 1000 -> x = 500, y = 2000
    sqrt_p = 2 * Q96
    assert pd_.v4_token_reserve(1000, sqrt_p, True) == pytest.approx(500)
    # token is currency1: price of token in currency0 = 1/4, its reserve = L * sqrtP = 2000
    assert pd_.v4_token_reserve(1000, sqrt_p, False) == pytest.approx(2000)
    assert pd_.v4_token_reserve(0, sqrt_p, True) == 0


def test_pool_modify_only_in_range():
    hexw = lambda v: format(v % (1 << 256), "064x")  # noqa: E731
    p = pd_.Pool(True, Q96, 0)
    p.apply("modify", [hexw(-100), hexw(100), hexw(500)])
    p.apply("modify", [hexw(200), hexw(300), hexw(999)])  # out of range
    assert p.liq == 500
    p.apply("modify", [hexw(-100), hexw(100), hexw(-200)])
    assert p.liq == 300
    p.apply("swap", [hexw(0), hexw(0), hexw(Q96 * 2), hexw(700), hexw(-5)])
    assert (p.liq, p.tick, p.sqrt_p) == (700, -5, 2 * Q96)


def test_curve_fit_recovers_reserves():
    y0, x0 = 1.5e18, 1.0e27
    k, y, trades = x0 * y0, y0, []
    rng = np.random.default_rng(1)
    for _ in range(40):
        if rng.random() < 0.7 or y < 2 * y0:
            de = rng.uniform(1e15, 3e17)
            trades.append((True, de, k / y - k / (y + de)))
            y += de
        else:
            dt = rng.uniform(1e23, 5e24)
            de = y - k / (k / y + dt)
            trades.append((False, de, dt))
            y -= de
    fy0, fk, spread = pd_.fit_curve(trades)
    assert fy0 == pytest.approx(y0, rel=0.01)
    assert fk == pytest.approx(k, rel=0.02)
    assert spread < 1e-3
    assert pd_.curve_token_reserve(trades, fy0, fk, len(trades)) == pytest.approx(k / y, rel=0.02)


def test_net_measured_depth_equals_guess_when_same():
    d, pa = 3000.0, 1e-6
    guess = scorecard.net(100, d, [(1.0, 5 * pa)], pa, pa)
    measured = scorecard.net(100, d, [(1.0, 5 * pa, d * 5 ** 0.5)], pa, pa, d)
    assert measured == pytest.approx(guess)
    # a thinner pool at the sale gives less back; NaN falls back to the guess
    assert scorecard.net(100, d, [(1.0, 5 * pa, 500.0)], pa, pa, d) < guess
    assert scorecard.net(100, d, [(1.0, 5 * pa, np.nan)], pa, pa, np.nan) == pytest.approx(guess)
