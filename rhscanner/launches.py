"""Local index of every Pons V2 launch (token -> curve, launcher, block).

Asking the node for one launcher's history directly means scanning weeks of
blocks with a topic filter, which the public RPC often times out on. Pons
launches are frequent (thousands a day) but tiny, so instead the bot tails the
factory's launch events into SQLite (and backfills the lookback once, a few
queries per round, in the background); a launcher's history is then one local
query. See checks/deployer.py.
"""

import logging

from .checks.deployer import LOOKBACK_BLOCKS, PONS_V2_FACTORY, PONS_V2_LAUNCH

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pons_launches (
    token TEXT PRIMARY KEY,
    launcher TEXT NOT NULL,
    block INTEGER NOT NULL,
    curve TEXT
);
CREATE INDEX IF NOT EXISTS pons_launches_launcher ON pons_launches (launcher);
CREATE INDEX IF NOT EXISTS pons_launches_block ON pons_launches (block);
CREATE TABLE IF NOT EXISTS pons_index (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""

WINDOW_BLOCKS = 100_000  # up to ~2.5k launches at peak rates; the node caps a query at 10k logs
MIN_WINDOW_BLOCKS = 500
BACKFILL_STEPS = 20  # backfill queries per sync round


class LaunchIndex:
    def __init__(self, db, lookback: int = LOOKBACK_BLOCKS):
        self.db = db
        self.lookback = lookback
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(pons_launches)")}
        if "curve" not in columns:  # indexes made before the curve was kept
            self.db.execute("ALTER TABLE pons_launches ADD COLUMN curve TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS pons_launches_curve ON pons_launches (curve)")
        self.db.commit()

    def _get(self, key: str) -> int | None:
        row = self.db.execute("SELECT value FROM pons_index WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: int):
        self.db.execute("INSERT OR REPLACE INTO pons_index (key, value) VALUES (?, ?)", (key, value))

    async def _fetch(self, rpc, lo: int, hi: int) -> list[dict]:
        """Launch logs in [lo, hi]; ranges the node refuses (too many logs, timeout) are split in halves."""
        try:
            return await rpc.get_logs(lo, hi, [PONS_V2_LAUNCH], address=PONS_V2_FACTORY, retries=2)
        except Exception:
            if hi - lo < MIN_WINDOW_BLOCKS:
                raise
        mid = (lo + hi) // 2
        return await self._fetch(rpc, lo, mid) + await self._fetch(rpc, mid + 1, hi)

    def _store(self, logs: list[dict]):
        rows = []
        for entry in logs:
            topics = entry.get("topics") or []
            if len(topics) >= 4:
                rows.append(("0x" + topics[1][-40:].lower(), "0x" + topics[3][-40:].lower(),
                             int(entry["blockNumber"], 16), "0x" + topics[2][-40:].lower()))
        self.db.executemany(
            "INSERT OR IGNORE INTO pons_launches (token, launcher, block, curve) VALUES (?, ?, ?, ?)", rows
        )

    async def sync(self, rpc, head: int | None = None, backfill_steps: int = BACKFILL_STEPS) -> int:
        """Catch up to the head, then backfill a few windows. Returns the number of queries made."""
        head = head if head is not None else await rpc.block_number()
        high, low = self._get("high"), self._get("low")
        if high is None:
            high, low = head - 1, head  # nothing covered yet
        queries = 0
        while high < head:  # forward
            hi = min(head, high + WINDOW_BLOCKS)
            self._store(await self._fetch(rpc, high + 1, hi))
            high = hi
            self._set("high", high)
            self._set("low", low)
            self.db.commit()
            queries += 1
        floor = max(0, head - self.lookback)
        while low > floor and queries < backfill_steps:  # backward
            lo = max(floor, low - WINDOW_BLOCKS)
            self._store(await self._fetch(rpc, lo, low - 1))
            low = lo
            self._set("low", low)
            self.db.commit()
            queries += 1
        self.db.execute("DELETE FROM pons_launches WHERE block < ?", (floor,))
        self.db.commit()
        return queries

    async def fill_curves(self, rpc, lo: int, hi: int) -> int:
        """Re-read the launches in [lo, hi] to add the curve to rows indexed before it was kept."""
        filled = 0
        for start in range(lo, hi + 1, WINDOW_BLOCKS):
            logs = await self._fetch(rpc, start, min(hi, start + WINDOW_BLOCKS - 1))
            self._store(logs)
            rows = [("0x" + e["topics"][2][-40:].lower(), "0x" + e["topics"][1][-40:].lower())
                    for e in logs if len(e.get("topics") or []) >= 4]
            filled += self.db.executemany(
                "UPDATE pons_launches SET curve = ? WHERE token = ? AND curve IS NULL", rows
            ).rowcount
            self.db.commit()
        return filled

    def covers(self, block: int) -> bool:
        low = self._get("low")
        return low is not None and low <= block

    def complete(self, head: int) -> bool:
        """Whether the backfill has reached the start of the lookback."""
        return self.covers(max(0, head - self.lookback))

    def launcher_of(self, token: str) -> str | None:
        row = self.db.execute("SELECT launcher FROM pons_launches WHERE token = ?", (token.lower(),)).fetchone()
        return row[0] if row else None

    def launches_by(self, launcher: str) -> dict[str, int]:
        rows = self.db.execute("SELECT token, block FROM pons_launches WHERE launcher = ?", (launcher.lower(),))
        return dict(rows.fetchall())

    def by_curve(self, curve: str) -> tuple[str, str, int] | None:
        """(token, launcher, launch block) of a bonding curve."""
        return self.db.execute(
            "SELECT token, launcher, block FROM pons_launches WHERE curve = ?", (curve.lower(),)
        ).fetchone()

    def curve_of(self, token: str) -> str | None:
        row = self.db.execute("SELECT curve FROM pons_launches WHERE token = ?", (token.lower(),)).fetchone()
        return row[0] if row else None

    def launches_since(self, launcher: str, block: int, until: int | None = None) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM pons_launches WHERE launcher = ? AND block >= ? AND block <= ?",
            (launcher.lower(), block, until if until is not None else 2**62),
        ).fetchone()[0]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM pons_launches").fetchone()[0]
