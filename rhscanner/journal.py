"""The user's own Fomo trades, picked up from the chain (/cuzdan, /islemlerim).

Every Fomo trade names the trader's wallet (fomo.py), so once the user tells
the bot their Fomo wallet, their buys and sells are recorded as they happen,
with the dollars that actually moved (the USDG leg, Fomo's fee included).
A coin's position is closed once at least 99% of the tokens bought were sold.
"""

import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS my_trades (
    tx TEXT NOT NULL,
    token TEXT NOT NULL,
    side TEXT NOT NULL,
    ts REAL NOT NULL,
    usd REAL,
    amount REAL NOT NULL,
    PRIMARY KEY (tx, token, side)
);
CREATE INDEX IF NOT EXISTS my_trades_token ON my_trades (token, ts);
"""
CLOSED_SHARE = 0.99


class Journal:
    def __init__(self, db):
        self.db = db
        self.db.executescript(SCHEMA)
        self.db.commit()

    def record(self, trade) -> bool:
        """A fomo.FomoTrade by the user's wallet; False if it was already recorded."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO my_trades (tx, token, side, ts, usd, amount) VALUES (?, ?, ?, ?, ?, ?)",
            (trade.tx_hash, trade.token.lower(), trade.side, trade.timestamp or time.time(), trade.usd,
             float(trade.amount)),
        )
        self.db.commit()
        return cur.rowcount == 1

    def positions(self, hours: float, now: float | None = None) -> list[dict]:
        """One row per coin first bought in the last `hours`: dollars in and out, and whether it is closed."""
        now = now or time.time()
        rows = self.db.execute(
            "SELECT token, MIN(ts), "
            "SUM(CASE WHEN side = 'buy' THEN usd END), SUM(CASE WHEN side = 'sell' THEN usd END), "
            "SUM(CASE WHEN side = 'buy' THEN amount ELSE 0 END), SUM(CASE WHEN side = 'sell' THEN amount ELSE 0 END), "
            "SUM(CASE WHEN usd IS NULL THEN 1 ELSE 0 END), MAX(ts) "
            "FROM my_trades GROUP BY token HAVING MIN(CASE WHEN side = 'buy' THEN ts END) >= ? ORDER BY MIN(ts)",
            (now - hours * 3600,),
        ).fetchall()
        out = []
        for token, first_ts, usd_in, usd_out, bought, sold, unpriced, last_ts in rows:
            closed = bought > 0 and sold >= CLOSED_SHARE * bought
            out.append({
                "token": token, "first_ts": first_ts, "last_ts": last_ts,
                "usd_in": usd_in or 0.0, "usd_out": usd_out or 0.0,
                "held_share": max(0.0, 1 - sold / bought) if bought else 0.0,
                "closed": closed, "unpriced": bool(unpriced),
                "pnl": round((usd_out or 0.0) - (usd_in or 0.0), 2) if closed else None,
            })
        return out


def summarize_closed(positions: list[dict]) -> dict:
    closed = [p for p in positions if p["closed"] and not p["unpriced"]]
    if not closed:
        return {"n": 0}
    pnls = [p["pnl"] for p in closed]
    delays = [p["delay_min"] for p in closed if p.get("delay_min") is not None]
    held = [(p["last_ts"] - p["first_ts"]) / 60 for p in closed]
    return {
        "n": len(closed),
        "pnl": round(sum(pnls), 2),
        "invested": round(sum(p["usd_in"] for p in closed), 2),
        "win_rate": round(100.0 * sum(1 for x in pnls if x > 0) / len(pnls), 1),
        "best": max(pnls),
        "worst": min(pnls),
        "avg_delay_min": round(sum(delays) / len(delays), 1) if delays else None,
        "avg_hold_min": round(sum(held) / len(held)),
    }
