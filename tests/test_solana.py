import base64
import struct

from rhscanner import solana


def _line(raw: bytes) -> str:
    return "Program data: " + base64.b64encode(raw).decode()


def test_b58_known_addresses():
    assert solana.b58(bytes(32)) == "1" * 32
    assert solana.b58(bytes([0, 0, 1])) == "112"


def test_decode_curve_trade_and_pumpswap_buy():
    mint, user, pool = bytes(range(1, 33)), bytes(range(33, 65)), bytes(range(65, 97))
    trade = (solana.TRADE + mint + struct.pack("<QQ", 2_000_000_000, 10**18) + b"\x01" + user
             + struct.pack("<qQQ", 1_759_000_000, 30 * 10**9, 2**63 + 5) + bytes(100))  # real events carry more fields
    buy = bytearray(solana.BUY + struct.pack("<qQQ", 1_759_000_001, 777, 0) + bytes(184 - 32))
    struct.pack_into("<Q", buy, 64, 123_456)  # quote amount in
    buy[120:152], buy[152:184] = pool, user
    logs = [f"Program {solana.PUMP} invoke [1]", "Program log: Instruction: Buy", _line(trade),
            f"Program {solana.PUMP} success", f"Program {solana.PUMPSWAP} invoke [1]", _line(bytes(buy)),
            "Program data: !!", f"Program {solana.PUMPSWAP} success",
            "Program Other111 invoke [1]", _line(trade), "Program Other111 success"]  # same event name elsewhere
    out = solana.decode(logs)
    assert [e["venue"] for e in out] == [1, 2]
    c, s = out
    assert c["mint"] == solana.b58(mint) and c["user"] == solana.b58(user) and c["side"] == 1
    assert (c["lamports"], c["tokens"], c["ts"], c["vsol"], c["vtok"]) == (2 * 10**9, 10**18, 1_759_000_000,
                                                                            30 * 10**9, 2**63 + 5)
    assert s["mint"] is None and s["pool"] == solana.b58(pool) and s["side"] == 1
    assert (s["lamports"], s["tokens"], s["ts"]) == (123_456, 777, 1_759_000_001)


def test_huge_amounts_are_stored(tmp_path):
    import asyncio

    col = solana.Collector(str(tmp_path / "s.db"))
    trade = (solana.TRADE + bytes(range(1, 33)) + struct.pack("<QQ", 1, 2**64 - 1) + b"\x00" + bytes(32)
             + struct.pack("<qQQ", 1, 2, 2**64 - 1) + bytes(100))
    asyncio.run(col.on_logs(5, "sig", [f"Program {solana.PUMP} invoke [1]", _line(trade)]))
    col.flush()
    row = col.db.execute("SELECT slot, side, tokens FROM trades").fetchone()
    assert row == (5, 0, float(2**64 - 1))
    assert col.minute["curve"] == 1


def test_decode_reserves_and_creators():
    mint, user, creator, pool = bytes(range(1, 33)), bytes(range(33, 65)), bytes(range(100, 132)), bytes(range(65, 97))
    trade = bytearray(solana.TRADE + mint + struct.pack("<QQ", 1, 2) + b"\x01" + user
                      + struct.pack("<qQQQQ", 7, 40 * 10**9, 600 * 10**12, 10 * 10**9, 0) + bytes(400))
    trade[177:209] = creator
    sell = bytearray(solana.SELL + struct.pack("<qQQ", 8, 5, 0) + bytes(441 - 32))
    struct.pack_into("<QQQ", sell, 48, 10**14, 9 * 10**10, 777)  # pool coin / SOL reserves, SOL out
    sell[120:152], sell[152:184], sell[312:344] = pool, user, creator
    logs = [f"Program {solana.PUMP} invoke [1]", _line(bytes(trade)), f"Program {solana.PUMP} success",
            f"Program {solana.PUMPSWAP} invoke [1]", _line(bytes(sell)), f"Program {solana.PUMPSWAP} success"]
    c, s = solana.decode(logs)
    assert (c["rsol"], c["rtok"], c["creator"]) == (10 * 10**9, 0, solana.b58(bytes(creator)))
    assert (s["side"], s["lamports"], s["vsol"], s["vtok"], s["creator"]) == (0, 777, 9 * 10**10, 10**14,
                                                                              solana.b58(bytes(creator)))


def test_collector_notes_creators_graduation_and_migrates_old_db(tmp_path):
    import asyncio
    import sqlite3

    old = sqlite3.connect(tmp_path / "s.db")  # the table as the first server version made it
    old.execute("""CREATE TABLE trades (slot INTEGER, ts INTEGER, sig TEXT, venue INTEGER, mint TEXT, side INTEGER,
                   user TEXT, lamports REAL, tokens REAL, vsol REAL, vtok REAL, pool TEXT)""")
    old.execute("CREATE TABLE pools (pool TEXT PRIMARY KEY, base TEXT, quote TEXT)")
    old.execute("INSERT INTO trades VALUES (1, 100, 's', 1, 'OLD', 1, 'u', 1, 1, 1, 1, NULL)")
    old.commit()
    old.close()
    col = solana.Collector(str(tmp_path / "s.db"))
    assert col.db.execute("SELECT mint, first_seen, creator, curve FROM mints").fetchall() == [("OLD", 100, None, 1)]
    creator = bytes(range(100, 132))
    trade = bytearray(solana.TRADE + bytes(range(1, 33)) + struct.pack("<QQ", 1, 2) + b"\x01" + bytes(32)
                      + struct.pack("<qQQQQ", 200, 1, 1, 85 * 10**9, 0) + bytes(400))
    trade[177:209] = creator
    asyncio.run(col.on_logs(5, "sig", [f"Program {solana.PUMP} invoke [1]", _line(bytes(trade))]))
    col.flush()
    mint = solana.b58(bytes(range(1, 33)))
    assert col.db.execute("SELECT creator, first_seen, complete_ts, curve FROM mints WHERE mint = ?", (mint,)).fetchone() \
        == (solana.b58(creator), 200, 200, 1)  # an empty curve: the coin graduates
    assert col.db.execute("SELECT rsol, rtok FROM trades WHERE mint = ?", (mint,)).fetchone() == (85e9, 0.0)


def test_oldest_transaction_lookup_pages_and_stops(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(solana, "LOOKUP_GAP", 0)
    col = solana.Collector(str(tmp_path / "s.db"))
    pages = {None: [{"signature": f"a{i}", "blockTime": 2000 - i} for i in range(1000)],
             "a999": [{"signature": f"b{i}", "blockTime": 999 - i} for i in range(10)]}

    async def rpc(method, params):
        return pages.get(params[1].get("before"), [])
    col.rpc = rpc
    assert asyncio.run(col.oldest("X")) == (990, None)
    monkeypatch.setattr(solana, "MAX_PAGES", 1)
    assert asyncio.run(col.oldest("X")) == (None, 1001)  # cut short: only "older than"
