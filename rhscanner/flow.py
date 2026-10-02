"""Order-flow features of one coin's Fomo trades at a given moment.

Shared by the chain research (scripts/research_build.py, on downloaded trades) and the live bot, so a rule
found in the research is computed the same way when it runs. Inputs are one coin's trades, oldest first, as
parallel lists: time (s), side (1 buy / 0 sell), trader id, USD size (None if unknown), price (USD per raw
token unit, None if unknown).
"""

import bisect

SUPPLY_RAW = 1e9 * 1e18  # Pons coins: 1B tokens, 18 decimals


def last_price(side, price, i: int, buys_only: bool = True) -> float | None:
    for k in range(i, -1, -1):
        if price[k] and (side[k] or not buys_only):
            return price[k]
    return None


def flow_features(ts, side, trader, usd, price, i: int, first_ts: float, first_price: float | None,
                  wins=None, supply_raw: float | None = SUPPLY_RAW) -> dict:
    """Features at trade i (inclusive). `wins(trader, t)`: the trader's past early-buy wins known at t;
    `supply_raw`: the coin's total supply in raw units (FDV = price per raw unit x supply; None: unknown)."""
    t = ts[i]
    lo30 = bisect.bisect_right(ts, t - 1800)
    b1, b5, prev5, b10, b30 = set(), set(), set(), set(), set()
    sellers5, sellers30 = set(), set()
    per_buyer: dict = {}
    usd5 = usd10 = sell10 = 0.0
    buys5 = sells5 = 0
    for j in range(lo30, i + 1):
        age = t - ts[j]
        who = trader[j]
        if side[j]:
            b30.add(who)
            if age < 600:
                b10.add(who)
                usd10 += usd[j] or 0
                per_buyer[who] = per_buyer.get(who, 0) + (usd[j] or 0)
                if age < 300:
                    b5.add(who)
                    usd5 += usd[j] or 0
                    buys5 += 1
                    if age < 60:
                        b1.add(who)
                else:
                    prev5.add(who)
        else:
            sellers30.add(who)
            if age < 600:
                sell10 += usd[j] or 0
            if age < 300:
                sellers5.add(who)
                sells5 += 1
    p_now = last_price(side, price, i)
    j5 = bisect.bisect_right(ts, t - 300) - 1
    p_5 = last_price(side, price, j5) if j5 >= 0 else None
    out = {
        "b1": len(b1), "b5": len(b5), "prev5": len(prev5), "b10": len(b10), "b30": len(b30),
        "buys5": buys5, "sells5": sells5, "sellers5": len(sellers5),
        "usd5": usd5, "usd10": usd10, "sell10": sell10,
        "avg10": usd10 / len(b10) if b10 else 0.0,
        "whale10": max(per_buyer.values()) / usd10 if per_buyer and usd10 else 0.0,
        "hold30": 1 - len(b30 & sellers30) / len(b30) if b30 else 1.0,
        "buy_ratio10": usd10 / (usd10 + sell10) if usd10 + sell10 else 1.0,
        "age_min": (t - first_ts) / 60,
        "runup": p_now / first_price if p_now and first_price else 1.0,
        "chg5": p_now / p_5 if p_now and p_5 else 1.0,
        "fdv": p_now * supply_raw if p_now and supply_raw else float("nan"),
    }
    if wins is not None:
        scores = [wins(w, t) for w in b10]
        out["smart10"] = sum(1 for s in scores if s >= 2)
        out["smart_wins10"] = sum(scores)
    return out
