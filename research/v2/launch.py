"""Tokenin ilk işlemi: oluşturma anı, slotu ve yaratıcısı (ilk işlemin imzalayanı) → launch.json (önbellekli)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hl
from concurrent.futures import ThreadPoolExecutor
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch.json")

def first_tx(mint):
    r = hl.rpc("getTransactionsForAddress", [mint, {"limit": 1, "sortOrder": "asc", "transactionDetails": "full",
               "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
    if not r or not r.get("data"): return None
    tx = r["data"][0]
    return [tx["blockTime"], tx["slot"], tx["transaction"]["message"]["accountKeys"][0]["pubkey"]]

def update(mints):
    db = json.load(open(PATH)) if os.path.exists(PATH) else {}
    todo = [m for m in set(mints) if m not in db]
    with ThreadPoolExecutor(6) as ex:
        for m, r in zip(todo, ex.map(first_tx, todo)):
            if r: db[m] = r
    json.dump(db, open(PATH, "w"), separators=(",", ":"))
    print("lansman bilgisi", len(db), "token, yeni çağrı", hl.CALLS["n"])
    return db

if __name__ == "__main__":
    c = json.load(open(os.path.join(os.path.dirname(PATH), "candidates.json")))
    update({m for r in c for m in r["mints"]})
