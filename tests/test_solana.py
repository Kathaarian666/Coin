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
