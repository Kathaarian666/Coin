import json, time, threading, urllib.request, os
def _key():
    if os.environ.get("HELIUS_API_KEY"): return os.environ["HELIUS_API_KEY"]
    for f in (os.path.join(os.path.dirname(__file__), ".env"), os.path.join(os.path.dirname(__file__), "..", ".env")):
        if os.path.exists(f):
            for l in open(f):
                if l.startswith("HELIUS_API_KEY="): return l.split("=",1)[1].split(" #")[0].strip()
    raise SystemExit("HELIUS_API_KEY bulunamadı (.env dosyasına ya da ortam değişkenine yaz)")
KEY = _key()
RPC = f"https://mainnet.helius-rpc.com/?api-key={KEY}"
_lock = threading.Lock(); _last = [0.0]; MIN_GAP = 0.11  # ~9 req/s
CALLS = {"n": 0}

def _throttle():
    with _lock:
        now = time.time(); wait = _last[0] + MIN_GAP - now
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()

def rpc(method, params, tries=6):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for i in range(tries):
        _throttle(); CALLS["n"] += 1
        try:
            req = urllib.request.Request(RPC, data=body, headers={"content-type": "application/json", "User-Agent": "scan/1"})
            d = json.load(urllib.request.urlopen(req, timeout=40))
            if "error" in d:
                if d["error"].get("code") in (429, -32429): time.sleep(1.5 * (i + 1)); continue
                return None
            return d["result"]
        except Exception as e:
            time.sleep(1.5 * (i + 1))
    return None

def oldest_sigs(addr, want=600, max_pages=900):
    """Page getSignaturesForAddress back to the very first signature; return the oldest `want` (oldest first)."""
    before = None; tail = []; pages = 0
    while pages < max_pages:
        p = {"limit": 1000}
        if before: p["before"] = before
        r = rpc("getSignaturesForAddress", [addr, p]); pages += 1
        if r is None: return None, pages
        if not r: break
        tail = (tail + r)[-(want + 1000):]
        before = r[-1]["signature"]
        if len(r) < 1000: break
    tail = [x for x in tail if x.get("err") is None]
    return list(reversed(tail))[:want], pages

def get_tx(sig):
    return rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
