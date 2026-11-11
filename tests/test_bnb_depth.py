"""scripts/bnb_depth.py: a flap.sh curve trade is priced from the portal's V2-style pair (PROJE.md §4.17)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bnb_depth as bd  # noqa: E402

COIN = "0x" + "77" * 20
QUOTE = "0x" + "20" * 20
PAIR = "0x" + "79" * 20
USER = "0x" + "aa" * 20


def topic(addr):
    return "0x" + "0" * 24 + addr[2:]


def data(*vals):
    return "0x" + "".join(f"{v:064x}" for v in vals)


def test_flap_curve_is_priced_from_the_portal_pair_and_the_quote_price_table():
    E18 = 10 ** 18
    L = [
        (100, 1, QUOTE, [bd.TRANSFER, topic(USER), topic(bd.FLAP_PORTAL)], data(E18 // 100)),
        (100, 2, COIN, [bd.TRANSFER, topic(bd.FLAP_PORTAL), topic(USER)], data(10 ** 6 * E18)),
        (100, 3, PAIR, [bd.V2_SYNC], data(6 * E18, 900 * 10 ** 6 * E18)),  # token0 = QUOTE (sorted below COIN)
        (100, 4, PAIR, [bd.V2_SWAP, topic(bd.FLAP_PORTAL), topic(USER)], data(E18 // 100, 0, 0, 10 ** 6 * E18)),
    ]
    s = bd.sample(COIN, L, 800.0, known={QUOTE: 750.0 / E18})
    assert s is not None
    b, px, depth, kind, addr, fee = s
    assert (kind, addr) == ("curve", PAIR)
    assert abs(px * E18 - 6 / 900e6 * 750) < 1e-15  # $ per token = quote reserve / coin reserve x quote $
    assert abs(depth - 6 * 750) < 1e-6
    assert bd.sample(COIN, L, 800.0) is None  # the quote token unpriced -> no sample
