import asyncio
import importlib.util
import sqlite3
import sys
from pathlib import Path

from rhscanner import bnb, solana_export

USER, TOKEN = "0x" + "a" * 40, "0x" + "1" * 36 + "7777"


def _w(x) -> str:
    return format(x, "064x") if isinstance(x, int) else "0" * 24 + x[2:]


def _fomo(block, li, emitter, src, dst, token, amount, tx="0xt1"):
    return {"address": emitter, "blockNumber": hex(block), "logIndex": hex(li), "transactionHash": tx,
            "data": "0x" + _w(src) + _w(dst) + _w(token) + _w(amount) + _w(160) + _w(0)}


def _launch(block, token, creator, name="Coin", symbol="CN"):
    def s(text):
        b = text.encode()
        return _w(len(b)) + b.ljust(32 * ((len(b) + 31) // 32), b"\0").hex()
    name_s, sym_s, meta_s = s(name), s(symbol), s("ipfs")
    head = [_w(1_791_000_000), _w(creator), _w(7), _w(token)]
    off = 32 * 7
    offs = [off, off + len(name_s) // 2, off + len(name_s) // 2 + len(sym_s) // 2]
    data = "".join(head) + "".join(_w(o) for o in offs) + name_s + sym_s + meta_s
    return {"address": bnb.FLAP_PORTAL, "blockNumber": hex(block), "logIndex": "0x0", "transactionHash": "0xl",
            "data": "0x" + data}


def test_parsers():
    e = _fomo(10, 3, bnb.FOMO_EXECUTOR, bnb.FOMO_EXECUTOR, USER, TOKEN, 10**30)
    assert bnb.parse_fomo(e) == (bnb.FOMO_EXECUTOR, bnb.FOMO_EXECUTOR, USER, TOKEN, 1e30)
    assert bnb.parse_launch(_launch(5, TOKEN, USER, "一枚硬币", "改变")) == (TOKEN, USER, "一枚硬币", "改变")


class FakeRpc:
    def __init__(self, head):
        self.head = head
        self.queries = []

    async def __call__(self, method, params):
        if method == "eth_getBlockByNumber":
            return {"number": hex(self.head), "timestamp": hex(1_791_000_000 + self.head // 2)}
        q = params[0]
        self.queries.append((int(q["fromBlock"], 16), int(q["toBlock"], 16), q["address"]))
        lo, hi = int(q["fromBlock"], 16), int(q["toBlock"], 16)
        out = []
        if q["address"] == [bnb.FOMO_ENTRY, bnb.FOMO_EXECUTOR] and lo <= 950 <= hi:
            out = [_fomo(950, 1, bnb.FOMO_ENTRY, USER, bnb.FOMO_EXECUTOR, bnb.USDC, 5 * 10**18),
                   _fomo(950, 2, bnb.FOMO_EXECUTOR, bnb.FOMO_EXECUTOR, USER, TOKEN, 10**24)]
        elif q["address"] == bnb.USDC and lo <= 960 <= hi:
            out = [{"blockNumber": hex(960), "logIndex": "0x5", "transactionHash": "0xu", "data": hex(3 * 10**18),
                    "topics": [bnb.TRANSFER, "0x" + _w(USER), "0x" + _w(bnb.FOMO_EXECUTOR)]}]
        elif q["address"] == bnb.FLAP_PORTAL and lo <= 940 <= hi:
            out = [_launch(940, TOKEN, USER)]
        return out


def test_collector_polls_new_blocks_and_stores_everything(tmp_path):
    col = bnb.Collector(str(tmp_path / "b.db"))
    col.rpc = FakeRpc(1000)
    asyncio.run(col.step())
    assert col.done == 1000 and col.rpc.queries[0][0] == 1000 - bnb.START_BACK
    db = col.db
    assert db.execute("SELECT block, li, token, amount FROM fomo ORDER BY li").fetchall() == \
        [(950, 1, bnb.USDC, 5e18), (950, 2, TOKEN, 1e24)]
    assert db.execute("SELECT src, amount FROM usdc_in").fetchall() == [(USER, 3e18)]
    assert db.execute("SELECT token, creator, name FROM launches").fetchall() == [(TOKEN, USER, "Coin")]
    ts = db.execute("SELECT ts FROM fomo LIMIT 1").fetchone()[0]
    assert abs(ts - (1_791_000_500 - 50 * 0.45)) < 1e-6  # no earlier head yet: 0.45 s blocks back from the head
    # the next poll continues after the last block and interpolates between the two heads
    col.rpc = FakeRpc(1900)
    asyncio.run(col.step())
    assert col.rpc.queries[0][0] == 1001 and col.done == 1900 and col.prev == (1900, 1_791_000_950)
    col.prev = (1000, 1_791_000_500)  # between two polled heads: linear
    assert col.ts_of(1450, (1900, 1_791_000_950)) == 1_791_000_500 + 450 * 450 / 900


def test_bnb_export_and_import_round_trip(tmp_path):
    col = bnb.Collector(str(tmp_path / "b.db"))
    col.rpc = FakeRpc(1000)
    asyncio.run(col.step())
    db = col.db
    day = solana_export.pending_days(db, 2e9, "bnb")[0]
    assert solana_export.write_day(db, day, tmp_path / "veri", "bnb") == 2
    spec = importlib.util.spec_from_file_location("solana_import", Path(__file__).parents[1] / "scripts" / "solana_import.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old, sys.argv = sys.argv, [None, str(tmp_path / "veri"), str(tmp_path / "r.db"), "--chain", "bnb"]
    try:
        mod.main()
    finally:
        sys.argv = old
    r = sqlite3.connect(tmp_path / "r.db")
    assert r.execute("SELECT * FROM fomo ORDER BY li").fetchall() == db.execute("SELECT * FROM fomo ORDER BY li").fetchall()
    assert r.execute("SELECT * FROM launches").fetchall() == db.execute("SELECT * FROM launches").fetchall()
    assert r.execute("SELECT COUNT(*) FROM usdc_in").fetchone()[0] == 1
