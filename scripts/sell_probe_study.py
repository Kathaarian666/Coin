"""V4 sell simulation feasibility (PROJE.md §4.1): at the alert block and 1 / 6 / 24 h later, can a holder sell?

  python scripts/sell_probe_study.py <trades.db> <security.parquet>   (needs security_extra.py columns b0, first_block)

contracts/V4SellProbe.sol is put at a real holder's address through an eth_call state override (nothing is sent)
and sells a tenth of the holder's coins into the coin's latest V4 pool (Initialize events up to the alert).
Historical blocks need dRPC: the public node keeps no old state. Result per coin and lag: ✓ sold, ✗ reverted,
"çıktı 0" = the swap gave nothing back (liquidity gone), "holder yok" / "havuz yok" = could not be tried.
"""
import json, sqlite3, sys, urllib.request
from pathlib import Path
import pandas as pd
from eth_abi import encode, decode
from eth_utils import function_signature_to_4byte_selector, to_checksum_address

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rhscanner.config import DEFAULT_V4_POOL_MANAGER as PM
from rhscanner.hooks import TOPIC_V4_INITIALIZE as INIT

URL = "https://rpc.mainnet.chain.robinhood.com"
DRPC = "https://robinhood.drpc.org"  # keeps historical state, the public node does not
CODE = json.load(open(Path(__file__).resolve().parents[1] / "contracts" / "build" / "V4SellProbe.json"))["deployedBytecode"]
SEL = function_signature_to_4byte_selector("sell(address,(address,address,uint24,int24,address),address,uint256)")
SYSTEM = {"0x" + "0" * 40, "0x000000000000000000000000000000000000dead", PM.lower()}


def rpc(method, params, url=URL):
    for _ in range(6):
        try:
            req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         {"content-type": "application/json", "user-agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            import time; time.sleep(3)
    return {"error": "rpc"}


def pools(token, lo, hi):
    t = "0x" + "0" * 24 + token[2:]
    out = []
    for topics in ([INIT, None, t], [INIT, None, None, t]):
        r = rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "address": PM, "topics": topics}]).get("result") or []
        for e in r:
            d = bytes.fromhex(e["data"][2:])
            fee, ts, hooks = int.from_bytes(d[0:32], "big"), int.from_bytes(d[32:64], "big", signed=True), "0x" + d[76:96].hex()
            out.append((int(e["blockNumber"], 16), ("0x" + e["topics"][2][-40:], "0x" + e["topics"][3][-40:], fee, ts, hooks)))
    return [k for _, k in sorted(out)][::-1]


def balance(token, who, block="latest"):
    data = "0x70a08231" + "0" * 24 + who[2:]
    r = rpc("eth_call", [{"to": token, "data": data}, block], DRPC).get("result")
    return int(r, 16) if r and r != "0x" else 0


def holders(db, token):
    rows = db.execute("SELECT src, dst, value FROM transfers WHERE token = ?", (token,)).fetchall()
    bal = {}
    for s, d, v in rows:
        bal[s] = bal.get(s, 0) - v
        bal[d] = bal.get(d, 0) + v
    return [a for a, v in sorted(bal.items(), key=lambda x: -x[1]) if v > 0 and a not in SYSTEM and a != token][:8]


def probe(token, key, holder, amount, block="latest"):
    args = encode(["address", "(address,address,uint24,int24,address)", "address", "uint256"],
                  [to_checksum_address(PM), tuple(to_checksum_address(x) if i in (0, 1, 4) else x for i, x in enumerate(key)),
                   to_checksum_address(token), amount])
    call = {"from": "0x00000000000000000000000000000000c0ffee02", "to": holder, "data": "0x" + (SEL + args).hex(), "gas": hex(5_000_000)}
    r = rpc("eth_call", [call, block, {holder: {"code": CODE}}], DRPC)
    if "result" not in r:
        return "rpc-hata", str(r.get("error"))[:80]
    (sent, arrived, out, used), failed, reason = decode(["(uint256,uint256,uint256,uint256)", "uint8", "bytes"], bytes.fromhex(r["result"][2:]))
    if failed:
        return "satış başarısız", reason[:4].hex()
    tax = 1 - arrived / sent if sent else 0
    return ("satılabilir" if out > 0 else "çıktı 0"), f"vergi %{100 * tax:.1f}, kullanılan %{100 * used / max(arrived, 1):.0f}"



def main():
    db = sqlite3.connect(sys.argv[1], timeout=60)
    df = pd.read_parquet(sys.argv[2])
    df = df[(df.obs_h >= 24) & ~df.pons]
    for name, g in {"satılamayan": df[df.unsellable], "satılabilen": df[(df.fomo_sellers >= 2) & ~df.trap]}.items():
        g = g.sample(min(20, len(g)), random_state=1)
        tab = []
        for r in g.itertuples():
            ks = pools(r.token, int(r.first_block) - 864000, int(r.b0))
            if not ks:
                tab.append([r.token[:10], "havuz yok", "", "", ""])
                continue
            hs = holders(db, r.token)
            row = [r.token[:10]]
            for lag_h in (0, 1, 6, 24):
                blk = hex(int(r.b0) + 1 + lag_h * 36000)
                got = next(((h, b) for h in hs for b in [balance(r.token, h, blk)] if b > 0), None)
                if not got:
                    row.append("holder yok")
                    continue
                o = probe(r.token, ks[0], got[0], max(1, got[1] // 10), blk)
                row.append({"satılabilir": "✓", "satış başarısız": "✗"}.get(o[0], o[0]))
            tab.append(row)
        print("==", name)
        print(pd.DataFrame(tab, columns=["coin", "an", "+1s", "+6s", "+24s"]).to_string(index=False))


if __name__ == "__main__":
    main()
