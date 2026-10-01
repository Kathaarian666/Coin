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


def let_winner_run(check_minutes: int, keep_above: float, else_minutes: int) -> Rule:
    """At `check_minutes`: sell unless it is at `keep_above`x or more; winners are held to `else_minutes`."""
    def rule(path, exit_min):
        at_check = _at(path, check_minutes)
        return [(1.0, at_check if at_check < keep_above else _at(path, else_minutes))]
    return rule


def until_exit(else_minutes: int) -> Rule:
    """Hold until the bot's 🔴 ÇIK (at its price), else sell at `else_minutes`."""
    return lambda path, exit_min: [(1.0, _at(path, exit_min if exit_min is not None else else_minutes))]


RULES: list[tuple[str, Rule]] = [
    ("30 dk tut, sat", hold(30)),
    ("1 saat tut, sat", hold(60)),
    ("2 saat tut, sat", hold(120)),
    ("4 saat tut, sat", hold(240)),
    ("24 saat tut, sat", hold(1440)),
    ("1 saatte 1.5x+ ise 4 saate kadar tut, değilse 1 saatte sat", let_winner_run(60, 1.5, 240)),
    ("2x'te yarısı, kalanı 1 saatte", take_profit(2.0, 60, share=0.5)),
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
            "without_best": round(sum(pnls) - max(pnls), 2),
            "exits": sum(1 for path, exit_min in paths if path and exit_min is not None),
            "n": len(pnls),
            "total": round(sum(pnls), 2),
            "per_trade": round(sum(pnls) / len(pnls), 2),
            "win_rate": round(100.0 * sum(1 for p in pnls if p > 0) / len(pnls), 1),
            "median": round(statistics.median(pnls), 2),
            "best": round(max(pnls), 2),
        }))
    return out


def target_exit(target: float, time_stop: int, stop: float | None = None) -> Rule:
    """Sell everything at `target` once two samples in a row reach it (one sample can be a spike on a thin pool
    that nobody could sell into), at the first sample at or under `stop` (at that sample's price), else at
    `time_stop` minutes."""
    def rule(path, exit_min):
        for i, (m, x) in enumerate(path):
            if m > time_stop:
                break
            if stop is not None and m > 0 and x <= stop:
                return [(1.0, x)]
            if x >= target and i + 1 < len(path) and path[i + 1][1] >= target:
                return [(1.0, target)]
        # at the time stop, no better than the next sample either: one high sample can be a spike
        after = [x for m, x in path if m > time_stop][:1]
        return [(1.0, min([_at(path, time_stop), *after]))]
    return rule


def delayed(path: list[tuple[int, float]], minutes: int = 5) -> list[tuple[int, float]]:
    """The same signal bought `minutes` later (at that sample's price): reaction time on a phone."""
    later = [(m, x) for m, x in path if m >= minutes]
    if not later or later[0][1] <= 0:
        return []
    m0, x0 = later[0]
    return [(m - m0, x / x0) for m, x in later]


TARGETS = (1.5, 2.0, 3.0)
TIME_STOPS = (30, 60, 120)
STOPS = (None, 0.7)
REFERENCE = (2.0, 60, None)


def target_rules() -> list[tuple[tuple[float, int, float | None], Rule]]:
    return [((t, m, s), target_exit(t, m, s)) for t in TARGETS for m in TIME_STOPS for s in STOPS]


def target_stats(paths: list[list[tuple[int, float]]], rule: Rule, position: float, fee_pct: float,
                 fee_min: float) -> dict:
    """$ result of one exit rule over signals (oldest first), overall and in the older / newer half."""
    pnls = [trade_pnl(rule(p, None), position, fee_pct, fee_min) for p in paths if p]
    if not pnls:
        return {"n": 0}
    half = len(pnls) // 2
    per = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
    return {"n": len(pnls), "per_trade": per(pnls), "total": round(sum(pnls), 2),
            "win_rate": round(100.0 * sum(1 for p in pnls if p > 0) / len(pnls), 1),
            "old": per(pnls[:half]), "new": per(pnls[half:])}


def held_hit(path: list[tuple[int, float]], target: float, within: int = 60) -> bool:
    """The price at `target`x or more in two samples in a row, the first within `within` minutes."""
    return any(m <= within and x >= target and b >= target for (m, x), (_, b) in zip(path, path[1:]))


def target_table(groups: list[tuple[str, list[list[tuple[int, float]]]]], position: float, fee_pct: float,
                 fee_min: float, top: int = 4) -> list[dict]:
    """/hedef: per group of signals (price paths, oldest first) how often 1.5x / 2x held within an hour, the
    reference rule (2x, else out at 60 min) and the best exit rules by $ per trade."""
    out = []
    for title, paths in groups:
        paths = [p for p in paths if p]
        row = {"title": title, "n": len(paths)}
        if paths:
            row["held15"] = round(100.0 * sum(held_hit(p, 1.5) for p in paths) / len(paths), 1)
            row["held2"] = round(100.0 * sum(held_hit(p, 2.0) for p in paths) / len(paths), 1)
            rules = [(key, target_stats(paths, rule, position, fee_pct, fee_min)) for key, rule in target_rules()]
            row["reference"] = dict(rules)[REFERENCE]
            row["best"] = sorted(rules, key=lambda kr: -kr[1]["per_trade"])[:top]
            late = [d for p in paths if (d := delayed(p))]
            best_key = row["best"][0][0]
            row["late"] = [(key, target_stats(late, target_exit(*key), position, fee_pct, fee_min))
                           for key in dict.fromkeys([REFERENCE, best_key])]
        out.append(row)
    return out


def rule_name(key: tuple[float, int, float | None]) -> str:
    target, minutes, stop = key
    text = f"{target:g}x'te sat, yoksa {minutes} dk'da çık"
    return text + (f", {stop:g}x'e düşerse kes" if stop else "")
