#!/usr/bin/env python3
"""
Kâğıt üstünde kopyalama (paper copy-trading) servisi — Solana.

Takip listesindeki cüzdanları Helius websocket ile dinler. Bir cüzdan bir token
aldığında, ayarlanan gecikmelerle (ör. 30 sn ve 2 dk) o anki piyasa fiyatından
SANAL bir pozisyon açar; cüzdan pozisyonunun yarısından fazlasını sattığında aynı
gecikmeyle sanal olarak çıkar. Sonuçları SQLite'a yazar ve Telegram'a bildirir.

GERÇEK İŞLEM YAPMAZ. Cüzdan, özel anahtar veya para kullanmaz.

Kullanım:
  python3 paper_copy.py            # servisi çalıştır
  python3 paper_copy.py rapor      # o ana kadarki sonuçları terminale yazdır
  python3 paper_copy.py test-tg    # Telegram'a deneme mesajı gönder
  python3 paper_copy.py replay SIG # geçmiş bir işlemi sinyal gibi işle (test)
"""
import asyncio, collections, html, json, os, sqlite3, statistics, sys, threading, time, urllib.request
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------- ayarlar
def load_env(path):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.split(" #")[0].split("\t#")[0].strip()   # satır sonu yorumlarını at
                os.environ.setdefault(k.strip(), v)

HERE = os.path.dirname(os.path.abspath(__file__))
load_env(os.path.join(HERE, ".env"))

HELIUS_KEY = os.environ.get("HELIUS_API_KEY", "")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
DELAYS = [int(x) for x in os.environ.get("DELAYS_SEC", "1,3,30").split(",")]
SIZE_SOL = float(os.environ.get("PAPER_SIZE_SOL", "0.5"))
FEE_SIDE = float(os.environ.get("FEE_PER_SIDE", "0.015"))      # ücret + kayma, tek yön
MIN_SOL = float(os.environ.get("MIN_SIGNAL_SOL", "0.2"))         # bundan küçük alımları yok say
EXIT_FRAC = float(os.environ.get("EXIT_SOLD_FRACTION", "0.5"))   # cüzdan bu oranı satınca çık
MAX_HOLD_H = float(os.environ.get("MAX_HOLD_HOURS", "48"))
POLL_SEC = int(os.environ.get("FALLBACK_POLL_SEC", "900"))
NOTIFY_SIGNALS = os.environ.get("NOTIFY_SIGNALS", "1") == "1"
REPORT_HOUR = int(os.environ.get("DAILY_REPORT_HOUR", "21"))      # İstanbul saati
TZ = timezone(timedelta(hours=3))
DB = os.path.join(HERE, os.environ.get("DB_FILE", "paper.db"))
WALLETS_FILE = os.path.join(HERE, os.environ.get("WALLETS_FILE", "wallets.txt"))

RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}"
WSS = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}"
WSOL = "So11111111111111111111111111111111111111112"
STABLE = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
          "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"}

def log(*a): print(datetime.now(TZ).strftime("%m-%d %H:%M:%S"), *a, flush=True)

def load_wallets():
    ws = {}
    for line in open(WALLETS_FILE):
        line = line.split("#")[0].strip()
        if not line: continue
        parts = line.split(None, 1)
        ws[parts[0]] = parts[1] if len(parts) > 1 else parts[0][:6]
    return ws

# ---------------------------------------------------------------- HTTP / RPC
_lock = threading.Lock(); _last = [0.0]; CALLS = collections.Counter()

def http_json(url, body=None, timeout=40):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", "User-Agent": "paper-copy/1"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def rpc(method, params, tries=5):
    for i in range(tries):
        with _lock:
            wait = _last[0] + 0.15 - time.time()
            if wait > 0: time.sleep(wait)
            _last[0] = time.time()
        CALLS[method] += 1
        try:
            d = http_json(RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            if "error" in d:
                if d["error"].get("code") in (429, -32429): time.sleep(2 * (i + 1)); continue
                log("rpc hata", method, d["error"]); return None
            return d["result"]
        except Exception as e:
            log("rpc istisna", method, e); time.sleep(2 * (i + 1))
    return None

def deltas(tx, w):
    """Cüzdanın bu işlemdeki SOL (+wSOL) ve token bakiye değişimleri."""
    m = tx["meta"]; d = collections.defaultdict(float)
    for b in m.get("preTokenBalances") or []:
        if b.get("owner") == w: d[b["mint"]] -= b["uiTokenAmount"]["uiAmount"] or 0
    for b in m.get("postTokenBalances") or []:
        if b.get("owner") == w: d[b["mint"]] += b["uiTokenAmount"]["uiAmount"] or 0
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    sol = 0.0
    if w in keys:
        i = keys.index(w); sol = (m["postBalances"][i] - m["preBalances"][i]) / 1e9
    sol += d.pop(WSOL, 0.0)
    return sol, {k: v for k, v in d.items() if abs(v) > 1e-9 and k not in STABLE}

def classify(tx, w):
    """SOL karşılığı tek tokenlık alım/satım ise (yon, mint, miktar, sol) döndür."""
    if not tx or tx["meta"].get("err"): return None
    sol, toks = deltas(tx, w)
    if len(toks) != 1 or abs(sol) < 0.002: return None
    (mint, q), = toks.items()
    if q > 0 and sol < 0: return ("BUY", mint, q, -sol)
    if q < 0 and sol > 0: return ("SELL", mint, -q, sol)
    return None

def pool_price(tx, mint):
    """Havuz rezervinden fiyat (SOL/token): işlemi yapanın tersine token değişimi olan sahip (havuz)
    SOL + wSOL değişimi / token değişimi. Ücret ve Jito bahşişi havuza gitmediği için fiyatı bozmaz."""
    m = tx["meta"]; tok = collections.defaultdict(float); wsol = collections.defaultdict(float)
    for sign, key in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in m.get(key) or []:
            amt = sign * (b["uiTokenAmount"]["uiAmount"] or 0)
            if b["mint"] == mint: tok[b.get("owner")] += amt
            elif b["mint"] == WSOL: wsol[b.get("owner")] += amt
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    pools = [(o, v) for o, v in tok.items() if o != keys[0] and abs(v) > 1e-9]
    if not pools: return None
    pool, pv = max(pools, key=lambda x: abs(x[1]))
    ps = wsol.get(pool, 0.0)
    if pool in keys:
        i = keys.index(pool); ps += (m["postBalances"][i] - m["preBalances"][i]) / 1e9
    if abs(ps) < 0.005 or (pv > 0) == (ps > 0): return None
    return abs(ps) / abs(pv)

def _swap_prices(txs, mint, t_lo, t_hi, n=3):
    px = []
    for tx in txs:
        if tx["meta"].get("err") or not (t_lo <= tx["blockTime"] <= t_hi): continue
        p = pool_price(tx, mint)
        if p: px.append(p)
        if len(px) >= n: break
    return statistics.median(px) if px else None

def price_at(mint, t):
    """t anındaki piyasa fiyatı (SOL/token): t'den sonraki 15 sn içindeki ilk 3 swap'ın havuz fiyatı medyanı;
    yoksa 60 sn içindeki ilk swap; o da yoksa t öncesindeki son swap."""
    base = {"limit": 100, "transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}
    txs = []; pg = None
    for _ in range(3):  # yoğun tokenlerde ilk sayfalar başarısız arbitraj denemeleriyle dolu olabiliyor
        o = dict(base, sortOrder="asc", filters={"blockTime": {"gte": int(t)}})
        if pg: o["paginationToken"] = pg
        r = rpc("getTransactionsForAddress", [mint, o]) or {}
        txs += r.get("data", []); pg = r.get("paginationToken")
        if not pg or not txs or txs[-1]["blockTime"] > t + 60 or _swap_prices(txs, mint, t, t + 15): break
    p = _swap_prices(txs, mint, t, t + 15) or _swap_prices(txs, mint, t, t + 60, n=1)
    if p: return p, "ileri"
    r = rpc("getTransactionsForAddress", [mint, dict(base, sortOrder="desc", filters={"blockTime": {"lte": int(t)}})])
    p = _swap_prices((r or {}).get("data", []), mint, t - 3600, t, n=1)
    return (p, "geri") if p else (None, None)

_sym = {}
def symbol(mint):
    if mint in _sym: return _sym[mint]
    s = mint[:6]
    try:
        req = urllib.request.Request(f"https://api.dexscreener.com/tokens/v1/solana/{mint}", headers={"User-Agent": "curl/8"})
        d = json.load(urllib.request.urlopen(req, timeout=15))
        if d: s = d[0]["baseToken"]["symbol"]
    except Exception: pass
    _sym[mint] = s; return s

# ---------------------------------------------------------------- Telegram
def tg(text):
    if not (TG_TOKEN and TG_CHAT):
        log("[TG kapalı]", text.replace("\n", " | ")); return
    try:
        http_json(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  {"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=20)
    except Exception as e:
        log("telegram hata", e)

def short(a): return a[:4] + "…" + a[-4:]
def esc(s): return html.escape(str(s), quote=False)
def link_tok(m): return f'<a href="https://dexscreener.com/solana/{m}">{esc(symbol(m))}</a>'
def link_tx(s): return f'<a href="https://solscan.io/tx/{s}">tx</a>'

# ---------------------------------------------------------------- veritabanı
def db():
    c = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    c.execute("""CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, wallet TEXT, label TEXT, mint TEXT,
        delay INTEGER, signal_t INTEGER, signal_sig TEXT, entry_t INTEGER, entry_px REAL, size_sol REAL, qty REAL,
        status TEXT, exit_t INTEGER, exit_px REAL, pnl_pct REAL, pnl_sol REAL, reason TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS seen(sig TEXT PRIMARY KEY, t INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS flow(wallet TEXT, mint TEXT, bought REAL, sold REAL, since INTEGER, PRIMARY KEY(wallet,mint))")
    c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    c.commit(); return c

DBC = None
DBL = threading.Lock()
def q(sql, args=(), fetch=False):
    with DBL:
        cur = DBC.execute(sql, args); DBC.commit()
        return cur.fetchall() if fetch else cur

# ---------------------------------------------------------------- iş mantığı
WALLETS = {}

def handle_sig(sig, wallet, now_live=True):
    if q("SELECT 1 FROM seen WHERE sig=?", (sig,), True): return
    q("INSERT OR IGNORE INTO seen VALUES(?,?)", (sig, int(time.time())))
    tx = rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
    if tx is None:  # RPC hatası ya da henüz indekslenmedi: yedek tarama tekrar denesin
        q("DELETE FROM seen WHERE sig=?", (sig,)); return
    c = classify(tx, wallet)
    if not c: return
    side, mint, qty, sol = c; t = tx["blockTime"]; label = WALLETS.get(wallet, short(wallet))
    if side == "BUY":
        if sol < MIN_SOL: return
        row = q("SELECT bought, sold FROM flow WHERE wallet=? AND mint=?", (wallet, mint), True)
        is_new = not row or row[0][1] >= EXIT_FRAC * row[0][0]  # yeni pozisyon mu, ekleme mi
        if is_new:
            q("INSERT OR REPLACE INTO flow VALUES(?,?,?,?,?)", (wallet, mint, qty, 0.0, t))
        else:
            q("UPDATE flow SET bought=bought+? WHERE wallet=? AND mint=?", (qty, wallet, mint))
        open_ = q("SELECT 1 FROM positions WHERE wallet=? AND mint=? AND status IN ('bekliyor','acik')", (wallet, mint), True)
        if is_new and not open_:
            if NOTIFY_SIGNALS:
                tg(f"🔔 <b>{esc(label)}</b> aldı: {link_tok(mint)} — {sol:.2f} SOL {link_tx(sig)}")
            for d in DELAYS:
                q("""INSERT INTO positions(wallet,label,mint,delay,signal_t,signal_sig,size_sol,status)
                     VALUES(?,?,?,?,?,?,?, 'bekliyor')""", (wallet, label, mint, d, t, sig, SIZE_SOL))
            log("SİNYAL AL", label, symbol(mint), f"{sol:.2f} SOL")
    else:
        row = q("SELECT bought, sold FROM flow WHERE wallet=? AND mint=?", (wallet, mint), True)
        if not row: return
        q("UPDATE flow SET sold=sold+? WHERE wallet=? AND mint=?", (qty, wallet, mint))
        bought, sold = row[0][0], row[0][1] + qty
        if bought > 0 and sold >= EXIT_FRAC * bought:
            n = q("UPDATE positions SET status='cikis_bekliyor', exit_t=? WHERE wallet=? AND mint=? AND status IN ('acik','bekliyor')",
                  (t, wallet, mint)).rowcount
            if n: log("SİNYAL SAT", label, symbol(mint), f"{sol:.2f} SOL")

def process_due():
    """Zamanı gelen sanal giriş/çıkışları gerçekleştir."""
    now = time.time()
    for (pid, mint, d, st, lbl, size) in q("SELECT id,mint,delay,signal_t,label,size_sol FROM positions WHERE status='bekliyor'", (), True):
        if now < st + d + 20: continue
        px, how = price_at(mint, st + d)
        if not px:
            if now > st + d + 300:
                q("UPDATE positions SET status='atlandi', reason='fiyat yok (likidite)' WHERE id=?", (pid,))
            continue
        qty = size * (1 - FEE_SIDE) / px
        q("UPDATE positions SET status='acik', entry_t=?, entry_px=?, qty=? WHERE id=?", (int(st + d), px, qty, pid))
        log("SANAL GİRİŞ", lbl, symbol(mint), f"+{d}s", f"{px:.3e}", how)
    for (pid, mint, d, et, lbl, epx, qty, size, st) in q(
            "SELECT id,mint,delay,exit_t,label,entry_px,qty,size_sol,signal_t FROM positions WHERE status='cikis_bekliyor'", (), True):
        if now < et + d + 20: continue
        if epx is None:
            # Cüzdan, bizim gecikmeli girişimizden önce satmış: kopyacı yine t+gecikme'de alır,
            # çıkışı da satış+gecikme'de yapar (gerçek bir kopyacının yaşayacağı durum).
            epx, _ = price_at(mint, st + d)
            if not epx:
                q("UPDATE positions SET status='atlandi', reason='fiyat yok (likidite)' WHERE id=?", (pid,)); continue
            qty = size * (1 - FEE_SIDE) / epx
            q("UPDATE positions SET entry_t=?, entry_px=?, qty=? WHERE id=?", (int(st + d), epx, qty, pid))
        close(pid, mint, d, et + d, lbl, epx, qty, size, "cüzdan sattı")
    for (pid, mint, d, lbl, epx, qty, size, ent) in q(
            "SELECT id,mint,delay,label,entry_px,qty,size_sol,entry_t FROM positions WHERE status='acik'", (), True):
        if ent and now > ent + MAX_HOLD_H * 3600:
            # sabit çıkış anı: fiyat bulunamazsa close() 600 sn sonra sıfır sayıp kapatır
            # (now kullanılırsa her 10 sn'de yeniden denenir ve kredi tüketir)
            close(pid, mint, d, ent + MAX_HOLD_H * 3600, lbl, epx, qty, size, f"süre doldu ({MAX_HOLD_H:.0f} sa)")

def close(pid, mint, d, t, lbl, epx, qty, size, reason):
    px, how = price_at(mint, t)
    if not px:
        if time.time() - t < 600: return
        px = 0.0; reason += ", fiyat yok → sıfır sayıldı"
    out = qty * px * (1 - FEE_SIDE); pnl = out - size; pct = pnl / size
    if pct > 20:  # 20 kattan fazla: büyük ihtimalle hatalı fiyat verisi, raporlara katma
        reason += ", ⚠️ şüpheli fiyat (raporlara katılmadı)"
    q("UPDATE positions SET status='kapali', exit_t=?, exit_px=?, pnl_pct=?, pnl_sol=?, reason=? WHERE id=?",
      (int(t), px, pct, pnl, reason, pid))
    emo = "🟢" if pnl > 0 else "🔴"
    tg(f"{emo} <b>{esc(lbl)}</b> {link_tok(mint)} (+{d}sn kopya): <b>{pct:+.0%}</b> ({pnl:+.3f} SOL) — {reason}")
    log("SANAL ÇIKIŞ", lbl, symbol(mint), f"+{d}s", f"{pct:+.1%}", reason)

def summary(since=None):
    rows = q("SELECT delay,pnl_pct,pnl_sol,label FROM positions WHERE status='kapali' AND pnl_pct<=20" + (" AND exit_t>=?" if since else ""),
             (since,) if since else (), True)
    lines = []
    for d in DELAYS:
        r = [x for x in rows if x[0] == d]
        if not r: lines.append(f"+{d}sn: henüz kapanan işlem yok"); continue
        p = [x[1] for x in r]
        lines.append(f"+{d}sn: {len(r)} işlem, kazanan %{100*sum(x>0 for x in p)/len(p):.0f}, "
                     f"medyan {statistics.median(p):+.0%}, toplam {sum(x[2] for x in r):+.2f} SOL")
    by = collections.defaultdict(list)
    for d_, p, s, lbl in rows:
        if d_ == DELAYS[0]: by[lbl].append(s)
    if by:
        lines.append(f"Cüzdan bazında (+{DELAYS[0]}sn):")
        for lbl, s in sorted(by.items(), key=lambda kv: -sum(kv[1])):
            lines.append(f"  {lbl}: {len(s)} işlem, {sum(s):+.2f} SOL")
    st = q("SELECT status, COUNT(*) FROM positions GROUP BY status", (), True)
    lines.append("Durum: " + ", ".join(f"{a}={b}" for a, b in st))
    return "\n".join(lines)

# ---------------------------------------------------------------- döngüler
async def ws_loop(queue):
    import websockets
    backoff = 2
    while True:
        try:
            async with websockets.connect(WSS, open_timeout=20, ping_interval=30, ping_timeout=30, max_size=2**22) as ws:
                subs = {}
                for i, w in enumerate(WALLETS):
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": i + 1, "method": "logsSubscribe",
                                              "params": [{"mentions": [w]}, {"commitment": "confirmed"}]}))
                ids = {i + 1: w for i, w in enumerate(WALLETS)}
                log(f"websocket bağlandı, {len(WALLETS)} cüzdan dinleniyor"); backoff = 2
                await queue.put(("POLL", None))  # kopukluk sırasında kaçanları topla
                async for raw in ws:
                    m = json.loads(raw)
                    if "id" in m and "result" in m and m["id"] in ids:
                        subs[m["result"]] = ids[m["id"]]; continue
                    p = m.get("params")
                    if not p: continue
                    v = p["result"]["value"]
                    if v.get("err"): continue
                    w = subs.get(p["subscription"])
                    if w: await queue.put((v["signature"], w))
        except Exception as e:
            log("websocket koptu:", e, f"— {backoff}s sonra yeniden")
            await asyncio.sleep(backoff); backoff = min(backoff * 2, 120)

def poll_once():
    """Websocket'in kaçırdığı işlemler için yedek tarama."""
    for w in WALLETS:
        r = rpc("getSignaturesForAddress", [w, {"limit": 15}])
        for x in reversed(r or []):
            if x.get("err") is None and x.get("blockTime", 0) > time.time() - 3600:
                handle_sig(x["signature"], w)

async def worker(queue):
    while True:
        sig, w = await queue.get()
        try:
            if sig == "POLL": await asyncio.to_thread(poll_once)
            else: await asyncio.to_thread(handle_sig, sig, w)
        except Exception as e:
            log("işlem hatası", sig, e)

async def timers(queue):
    last_poll = time.time()
    start = datetime.now(TZ)
    last_report_day = start.date() if start.hour >= REPORT_HOUR else None  # açılışta hemen rapor atma
    while True:
        await asyncio.sleep(10)
        try:
            await asyncio.to_thread(process_due)
        except Exception as e:
            log("zamanlayıcı hatası", e)
        if time.time() - last_poll > POLL_SEC:
            last_poll = time.time(); await queue.put(("POLL", None))
        now = datetime.now(TZ)
        if now.hour >= REPORT_HOUR and last_report_day != now.date():
            last_report_day = now.date()
            since = int((now - timedelta(days=1)).timestamp())
            tg("📊 <b>Günlük kâğıt kopyalama raporu</b> (son 24 saat)\n" + esc(summary(since)) +
               "\n\n<b>Başlangıçtan beri</b>\n" + esc(summary()) +
               f"\n\nAPI çağrısı (servis açıldığından beri): {sum(CALLS.values())}")

async def main():
    global WALLETS
    WALLETS = load_wallets()
    queue = asyncio.Queue()
    tg(f"▶️ Kâğıt kopyalama başladı: {len(WALLETS)} cüzdan, gecikmeler {', '.join(str(d)+'sn' for d in DELAYS)}, "
       f"işlem başı {SIZE_SOL} SOL (sanal). Gerçek işlem yapılmaz.")
    await asyncio.gather(ws_loop(queue), worker(queue), timers(queue))

if __name__ == "__main__":
    if not HELIUS_KEY: sys.exit("HELIUS_API_KEY eksik (.env dosyasına yaz)")
    DBC = db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "rapor": print(summary())
    elif cmd == "test-tg": tg("✅ Telegram bağlantısı çalışıyor (kâğıt kopyalama)")
    elif cmd == "replay":
        WALLETS = load_wallets()
        sig = sys.argv[2]
        tx = rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
        keys = [k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
        w = next((k for k in keys if k in WALLETS), keys[0])
        print("cüzdan", w, "sınıf", classify(tx, w)); handle_sig(sig, w)
    else:
        try: asyncio.run(main())
        except KeyboardInterrupt: pass
