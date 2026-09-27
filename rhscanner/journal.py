"""The user's own trades (/aldim, /sattim, /islemlerim), to compare real results with the simulations.

Prices are DexScreener's at the moment of the command; Fomo's fee (pct, with a
dollar minimum) is taken from the buy and from every sell, as in
exits.breakeven_multiple. One open position per coin: buying more adds to it.
"""

import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL,
    symbol TEXT,
    opened_ts REAL NOT NULL,
    usd REAL NOT NULL,          -- paid, fees included
    tokens REAL NOT NULL,       -- bought after the buy fee
    remaining REAL NOT NULL,    -- tokens still held
    entry_price REAL NOT NULL,
    alert_ts REAL,
    alert_price REAL,
    proceeds REAL NOT NULL DEFAULT 0,  -- received from sells, after fees
    closed_ts REAL
);
CREATE INDEX IF NOT EXISTS positions_open ON positions (token, closed_ts);
"""


def fee(amount: float, pct: float, minimum: float) -> float:
    return max(minimum, amount * pct / 100)


class Journal:
    def __init__(self, db, fee_pct: float = 0.5, fee_min: float = 0.95):
        self.db = db
        self.fee_pct, self.fee_min = fee_pct, fee_min
        self.db.executescript(SCHEMA)
        self.db.commit()

    def _open(self, token: str):
        return self.db.execute(
            "SELECT id, usd, tokens, remaining, entry_price FROM positions WHERE token = ? AND closed_ts IS NULL",
            (token.lower(),),
        ).fetchone()

    def buy(self, token: str, usd: float, price: float, symbol: str | None = None,
            alert: dict | None = None, now: float | None = None) -> dict:
        """alert: the coin's alert signal ({"ts", "p0"}) if the bot sent one."""
        now = now or time.time()
        invested = usd - fee(usd, self.fee_pct, self.fee_min)
        if invested <= 0:
            raise ValueError("tutar komisyonu karşılamıyor")
        tokens = invested / price
        row = self._open(token)
        if row:
            pid, _, old_tokens, _, old_entry = row
            entry = (old_entry * old_tokens + price * tokens) / (old_tokens + tokens)
            self.db.execute("UPDATE positions SET usd = usd + ?, tokens = tokens + ?, remaining = remaining + ?,"
                            " entry_price = ? WHERE id = ?", (usd, tokens, tokens, entry, pid))
        else:
            self.db.execute(
                "INSERT INTO positions (token, symbol, opened_ts, usd, tokens, remaining, entry_price, alert_ts,"
                " alert_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (token.lower(), symbol, now, usd, tokens, tokens, price,
                 (alert or {}).get("ts"), (alert or {}).get("p0")),
            )
        self.db.commit()
        out = {"usd": usd, "fee": round(usd - invested, 2), "price": price, "added": bool(row)}
        if alert and alert.get("p0"):
            out["vs_alert"] = price / alert["p0"]
            out["delay_min"] = (now - alert["ts"]) / 60
        return out

    def sell(self, token: str, share: float, price: float, now: float | None = None) -> dict | None:
        """Sell `share` (0-1] of what is left; returns the trade so far, or None without an open position."""
        row = self._open(token)
        if not row:
            return None
        pid, usd, tokens, remaining, entry = row
        sold = remaining * min(1.0, share)
        gross = sold * price
        net = max(0.0, gross - fee(gross, self.fee_pct, self.fee_min))
        left = remaining - sold
        closed = (now or time.time()) if left <= tokens * 1e-9 else None
        self.db.execute("UPDATE positions SET remaining = ?, proceeds = proceeds + ?, closed_ts = ? WHERE id = ?",
                        (0.0 if closed else left, net, closed, pid))
        self.db.commit()
        (proceeds,) = self.db.execute("SELECT proceeds FROM positions WHERE id = ?", (pid,)).fetchone()
        return {"net": round(net, 2), "multiple": price / entry, "closed": bool(closed),
                "pnl": round(proceeds - usd, 2) if closed else None, "left_share": left / tokens if tokens else 0,
                "usd": usd, "proceeds": round(proceeds, 2)}

    def open_positions(self) -> list[dict]:
        rows = self.db.execute("SELECT token, symbol, opened_ts, usd, tokens, remaining, entry_price, proceeds "
                               "FROM positions WHERE closed_ts IS NULL ORDER BY opened_ts").fetchall()
        keys = ("token", "symbol", "opened_ts", "usd", "tokens", "remaining", "entry_price", "proceeds")
        return [dict(zip(keys, r)) for r in rows]

    def value_now(self, position: dict, price: float) -> float:
        """What selling the rest now would bring, after the fee, plus what was already sold."""
        gross = position["remaining"] * price
        return max(0.0, gross - fee(gross, self.fee_pct, self.fee_min)) + position["proceeds"]

    def closed_summary(self, hours: float, now: float | None = None) -> dict:
        now = now or time.time()
        rows = self.db.execute(
            "SELECT usd, proceeds, opened_ts, alert_ts, alert_price, entry_price FROM positions "
            "WHERE closed_ts IS NOT NULL AND closed_ts >= ?", (now - hours * 3600,),
        ).fetchall()
        if not rows:
            return {"n": 0}
        pnls = [proceeds - usd for usd, proceeds, *_ in rows]
        delays = [(opened - alert_ts) / 60 for _, _, opened, alert_ts, _, _ in rows if alert_ts]
        vs_alert = [entry / alert_p for *_, alert_p, entry in rows if alert_p]
        return {
            "n": len(rows),
            "pnl": round(sum(pnls), 2),
            "invested": round(sum(usd for usd, *_ in rows), 2),
            "win_rate": round(100.0 * sum(1 for p in pnls if p > 0) / len(pnls), 1),
            "best": round(max(pnls), 2),
            "worst": round(min(pnls), 2),
            "avg_delay_min": round(sum(delays) / len(delays), 1) if delays else None,
            "avg_vs_alert": round(sum(vs_alert) / len(vs_alert), 2) if vs_alert else None,
        }
