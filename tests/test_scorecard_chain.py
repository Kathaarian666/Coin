"""scripts/scorecard.py block windows follow the chain's block rate (BNB's 0.45 s blocks, PROJE.md §4.17)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scorecard  # noqa: E402


def _trades():
    # ts, block, side (1 buy), usd, amount: flat price, no 5x
    return np.array([[t, 1000 + 10 * t, 1, 1.0, 1.0] for t in range(0, 20000, 60)], float)


def test_three_hour_exit_block_uses_the_chain_rate(monkeypatch):
    for chain, bps in (("robinhood", 9.93), ("bnb", 2.22)):
        monkeypatch.setattr(scorecard, "BPS", scorecard.CHAIN_BPS[chain])
        p = scorecard.path_of(_trades(), 600, 10)
        assert p["t5"] is None
        assert p["eb"] == p["ab"] + int(scorecard.HOLD * bps)
