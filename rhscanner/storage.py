"""SQLite persistence: scanner progress, seen tokens, reports and bot settings."""

import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens (
    address TEXT PRIMARY KEY,
    pool TEXT NOT NULL,
    first_seen REAL NOT NULL,
    block INTEGER,
    score INTEGER,
    report TEXT
);
CREATE TABLE IF NOT EXISTS alerts (address TEXT PRIMARY KEY, ts REAL NOT NULL);
"""


class Storage:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_state(self, key: str, value: str):
        self.db.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.db.commit()

    def mark_seen(self, address: str, pool: dict, block: int) -> bool:
        """Record a token and its pool; returns False if it was already known (analyse once)."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO tokens (address, pool, first_seen, block) VALUES (?, ?, ?, ?)",
            (address.lower(), json.dumps(pool), time.time(), block),
        )
        self.db.commit()
        return cur.rowcount == 1

    def mark_alerted(self, address: str) -> bool:
        """Returns True the first time a token is picked for an alert, False afterwards."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO alerts (address, ts) VALUES (?, ?)", (address.lower(), time.time())
        )
        self.db.commit()
        return cur.rowcount == 1

    def save_report(self, address: str, score: int, report: dict):
        self.db.execute(
            "INSERT INTO tokens (address, pool, first_seen, score, report) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(address) DO UPDATE SET score = excluded.score, report = excluded.report",
            (address.lower(), json.dumps(report.get("pool") or {}), time.time(), score, json.dumps(report)),
        )
        self.db.commit()

    def known_pool(self, address: str) -> dict | None:
        row = self.db.execute("SELECT pool FROM tokens WHERE address = ?", (address.lower(),)).fetchone()
        return (json.loads(row[0]) or None) if row else None

    def count_tokens(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
