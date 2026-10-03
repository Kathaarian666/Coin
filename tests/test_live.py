"""Real alerts (rhscanner/live.py): trust score, reasons, follow-ups."""

import asyncio
import json
import time

from rhscanner import live, paper
from rhscanner.bot import ScannerApp
from rhscanner.config import Settings


def report(codes=(), hooks=None, dev=0.0, proxy=None):
    return {"findings": [{"code": c} for c in codes], "liquidity": {"hooks": hooks} if hooks else {},
            "launch": {"dev_pct": dev}, "contract": {"proxy_implementation": proxy}}


def test_trust_score_falls_with_the_measured_risks():
    clean = live.trust_score(live.trust_flags(report(), 3, True, 5000.0))
    risky = live.trust_score(live.trust_flags(report(("owned", "fn_trading"), live.ZERO, 12.0, "0xabc"), 0, False, 300.0))
    assert 0 <= risky < clean <= 100
    assert live.trust_flags(report(hooks=live.ZERO), 0, False, None)["hook_yok"] == 1


def test_reasons_name_the_criteria_that_lift_the_score():
    class M:
        features = ["a", "b"]
        medians = {"a": 0.0, "b": 0.0}

        def score(self, f):
            return 0.1 + 0.5 * f["a"] + 0.01 * f["b"]
    got = live.reasons(M(), {"a": 1.0, "b": 1.0}, n=1)
    assert got == [("a", "1")]


def test_live_step_sends_2x_once(tmp_path):
    app = ScannerApp(Settings(db_path=str(tmp_path / "l.db")))
    sent = []

    async def fake_send(text, reply_to=None):
        sent.append(text)
        return {}
    app.send = fake_send

    async def sym(token):
        return "TST"
    app.symbol = sym
    token = "0x" + "4" * 40
    t0 = time.time() - 600
    app.follower.coins[token] = paper.Coin(t0, True, trades=[
        paper.Trade(t0, 1, 1, "a", 10.0, 10 ** 7), paper.Trade(t0 + 60, 2, 1, "b", 20.0, 10 ** 7),
        paper.Trade(t0 + 61, 3, 1, "c", 21.0, 10 ** 7)])
    app.live_log.add(token, t0, 1e-6, 1, None, {}, "ok")
    asyncio.run(app.live_step(time.time()))
    asyncio.run(app.live_step(time.time()))
    assert len(sent) == 1 and "2x" in sent[0]
    assert json.loads(app.live_log.db.execute("SELECT msg FROM live_log").fetchone()[0]) == {}
    asyncio.run(app.rpc.close())
