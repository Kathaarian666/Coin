import time

from rhscanner.checks.deployer import PONS_V2_LAUNCH
from rhscanner.config import Settings
from rhscanner.outcomes import OutcomeLog
from rhscanner.pons import CURVE_BUY
from rhscanner.pons_backfill import backfill, price_samples
from rhscanner.storage import Storage
from test_pons import CURVE, DEV, TOKEN, curve_log, launch_log

HEAD = 900_000
LAUNCH = HEAD - 400_000  # ~11 h ago
NOW = time.time()


class FakeRpc:
    def __init__(self, curve_logs):
        self.curve_logs = curve_logs

    async def block_number(self):
        return HEAD

    async def block_timestamp(self, number):
        return NOW - (HEAD - number) / 10

    async def get_logs(self, lo, hi, topics, address=None, retries=4):
        if topics[0] == PONS_V2_LAUNCH:
            return [launch_log(TOKEN, CURVE, DEV, LAUNCH)] if lo <= LAUNCH <= hi else []
        return [e for e in self.curve_logs if lo <= int(e["blockNumber"], 16) <= hi]


class FakeDex:
    async def tokens(self, addresses):
        weth = Settings().weth.lower()
        return [{"baseToken": {"address": weth}, "priceUsd": "2000", "liquidity": {"usd": 1e6}}] \
            if addresses == [weth] else []


def test_price_samples_stop_at_graduation_and_now():
    history = [(0.0, 1.0), (250.0, 2.0), (1000.0, 0.5)]
    assert price_samples(history, 0.0, now=1200, graduated_at=None) == {0: 1.0, 5: 2.0, 10: 2.0, 15: 2.0, 20: 0.5}
    assert price_samples(history, 0.0, now=1200, graduated_at=600) == {0: 1.0, 5: 2.0}


async def test_backfill_replays_signals_and_prices(tmp_path):
    buyers = [f"0x{i:040x}" for i in range(1, 11)]
    logs = [curve_log(CURVE_BUY, b, 0.02, 10, LAUNCH + 600 + i * 20) for i, b in enumerate(buyers)]
    logs.append(curve_log(CURVE_BUY, "0x" + "f" * 40, 0.3, 10, LAUNCH + 600 + 36_000))  # an hour later, 30x price
    storage = Storage(str(tmp_path / "b.db"))
    storage.db.execute("CREATE TABLE IF NOT EXISTS pons_launches (token TEXT PRIMARY KEY, launcher TEXT NOT NULL,"
                       " block INTEGER NOT NULL)")
    storage.db.execute("INSERT INTO pons_launches VALUES (?, ?, ?)", (TOKEN, DEV, LAUNCH))  # indexed without curve
    settings = Settings(pons_min_buyers=8, pons_min_buy_usd=100, pons_early_min_buyers=4, pons_early_min_buy_usd=50)
    result = await backfill(settings, FakeRpc(logs), storage, FakeDex(), days=0.5)
    assert result["by_kind"] == {"pons_early": 1, "pons": 1} and result["written"] == 2

    results = {r["kind"]: r for r in OutcomeLog(storage.db).results(hours=24)}
    assert results["pons"]["max_60"] == 15.0 and results["pons_early"]["ret_60"] == 15.0
    (done,) = storage.db.execute("SELECT MIN(next_idx) FROM signals").fetchone()
    assert done >= 13  # the ~11 h old signals continue live from the 12 h checkpoint

    again = await backfill(settings, FakeRpc(logs), storage, FakeDex(), days=0.5)
    assert again["signals"] == 0  # already recorded
    storage.close()
