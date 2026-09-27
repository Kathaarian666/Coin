"""Exit rules replayed on the recorded price paths of past alerts (/strateji).

Each alert has price samples at fixed minutes after it (outcomes.CHECKPOINTS_MIN).
A rule decides at which sample to sell (all or part); Fomo's fee is charged on
the buy and on every sell, like exits.breakeven_multiple. Samples are minutes
apart, so a target counts as hit at the first sample at or above it and sells
at the target (a resting limit order); what happened between samples is unknown.
"""

import statistics
from collections.abc import Callable

# path: [(minute, price / price at the alert)], oldest first; exit_min: minute of a 🔴 ÇIK, if one came
Rule = Callable[[list[tuple[int, float]], int | None], list[tuple[float, float]]]  # -> [(share sold, multiple)]


def _at(path, minute: int) -> float:
    """The multiple at the last sample at or before `minute` (the path's last one if it ends earlier)."""
    last = path[0][1]
    for m, x in path:
        if m > minute:
            break
        last = x
    return last


def hold(minutes: int) -> Rule:
    return lambda path, exit_min: [(1.0, _at(path, minutes))]


def take_profit(target: float, else_minutes: int, share: float = 1.0) -> Rule:
    """Sell `share` at `target` when a sample reaches it; everything left at `else_minutes`."""
    def rule(path, exit_min):
        hit = next((m for m, x in path if m <= else_minutes and x >= target), None)
        if hit is None:
            return [(1.0, _at(path, else_minutes))]
        return [(share, target)] + ([(1 - share, _at(path, else_minutes))] if share < 1 else [])
    return rule


def until_exit(else_minutes: int) -> Rule:
    """Hold until the bot's 🔴 ÇIK (at its price), else sell at `else_minutes`."""
    return lambda path, exit_min: [(1.0, _at(path, exit_min if exit_min is not None else else_minutes))]


RULES: list[tuple[str, Rule]] = [
    ("1 saat tut, sat", hold(60)),
    ("24 saat tut, sat", hold(1440)),
    ("2x'te sat (yoksa 1 saatte)", take_profit(2.0, 60)),
    ("2x'te sat (yoksa 24 saatte)", take_profit(2.0, 1440)),
    ("3x'te sat (yoksa 24 saatte)", take_profit(3.0, 1440)),
    ("5x'te sat (yoksa 24 saatte)", take_profit(5.0, 1440)),
    ("2x'te yarısı, kalanı 24 saatte", take_profit(2.0, 1440, share=0.5)),
    ("🔴 ÇIK gelince sat (yoksa 24 saatte)", until_exit(1440)),
]


def trade_pnl(sells: list[tuple[float, float]], position: float, fee_pct: float, fee_min: float) -> float:
    """Dollar result of buying `position` and selling it in the given (share, multiple) parts."""
    invested = position - max(fee_min, position * fee_pct / 100)
    proceeds = 0.0
    for share, multiple in sells:
        gross = invested * share * multiple
        proceeds += max(0.0, gross - max(fee_min, gross * fee_pct / 100)) if gross > 0 else 0.0
    return proceeds - position


def simulate(paths: list[tuple[list[tuple[int, float]], int | None]], position: float, fee_pct: float,
             fee_min: float) -> list[tuple[str, dict]]:
    out = []
    for name, rule in RULES:
        pnls = [trade_pnl(rule(path, exit_min), position, fee_pct, fee_min) for path, exit_min in paths if path]
        if not pnls:
            out.append((name, {"n": 0}))
            continue
        out.append((name, {
            "n": len(pnls),
            "total": round(sum(pnls), 2),
            "per_trade": round(sum(pnls) / len(pnls), 2),
            "win_rate": round(100.0 * sum(1 for p in pnls if p > 0) / len(pnls), 1),
            "median": round(statistics.median(pnls), 2),
            "best": round(max(pnls), 2),
        }))
    return out
