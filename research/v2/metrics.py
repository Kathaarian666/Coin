"""Ham swap listesinden cüzdan metrikleri; eğitim (ilk 14 gün) / test (son 7 gün) ayrımıyla.

Token başına kâr = satış SOL'u (alınan miktarı aşan satış orantılı kırpılır)
                 + elde kalan miktar × güncel fiyat (likidite < MIN_LIQ_USD ise sıfır) − alış SOL'u.
Token, ilk alımının olduğu döneme sayılır.
"""
import json, os, glob, statistics, collections

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DAYS = 7
MIN_LIQ_USD = 5000

def token_pnl(trades, px):
    """trades: o tokenin [t, side, qty, sol] listesi (zaman sıralı)."""
    bq = sq = bs = ss = 0.0; first = trades[0][0]; exit_t = None
    for t, side, q, s in trades:
        if side == "B": bq += q; bs += s
        else:
            sq += q; ss += s
            if exit_t is None and bq > 0 and sq >= 0.5 * bq: exit_t = t
    if bq <= 0: return None
    sold = ss * min(1.0, bq / sq) if sq > 0 else 0.0
    rem = max(0.0, bq - sq)
    p = px[0] if px and px[0] and (px[2] or 0) >= MIN_LIQ_USD else 0.0
    held_val = rem * p
    pnl = sold + held_val - bs
    return dict(first=first, cost=bs, pnl=pnl, roi=pnl / bs if bs else 0, held_frac=rem / bq,
                hold=(exit_t - first) if exit_t else None, nb=sum(1 for x in trades if x[1] == "B"))

def window_stats(toks, days):
    if not toks: return dict(n=0)
    pnls = [x["pnl"] for x in toks]; rois = [x["roi"] for x in toks]
    gp = sum(p for p in pnls if p > 0); gl = -sum(p for p in pnls if p < 0)
    top3 = sum(sorted(pnls, reverse=True)[:3])
    holds = [x["hold"] for x in toks if x["hold"] is not None]
    tot = sum(pnls)
    return dict(n=len(toks), pnl=round(tot, 2), cost=round(sum(x["cost"] for x in toks), 2),
                win=round(sum(p > 0 for p in pnls) / len(pnls), 2), med_roi=round(statistics.median(rois), 3),
                pf=round(gp / gl, 2) if gl > 0 else None, top3_share=round(top3 / tot, 2) if tot > 0 else None,
                med_cost=round(statistics.median(x["cost"] for x in toks), 3),
                med_hold_s=int(statistics.median(holds)) if holds else None,
                held_frac=round(sum(x["held_frac"] > 0.5 for x in toks) / len(toks), 2),
                tok_per_day=round(len(toks) / days, 1))

def wallet_metrics(d, prices, split=None, exclude=frozenset()):
    """split: eğitim/test sınırı (unix sn; varsayılan: son TEST_DAYS gün). exclude: hesaba katılmayan tokenler."""
    split = split or d["fetched"] - TEST_DAYS * 86400
    start = max(d["since"], d["oldest"] or d["fetched"]) if d["status"] == "sinir" else d["since"]
    by = collections.defaultdict(list)
    for t, mint, side, q, s, sig, signer in d["rows"]:
        by[mint].append((t, side, q, s))
    tr, te = [], []
    for mint, ts in by.items():
        if mint in exclude: continue
        r = token_pnl(ts, prices.get(mint))
        if r is None: continue
        (tr if r["first"] < split else te).append(r)
    act_days = len({int(x[0] // 86400) for x in d["rows"]})
    return dict(wallet=d["wallet"], status=d["status"], txs=d["txs"], swaps=len(d["rows"]),
                cover_days=round((d["fetched"] - start) / 86400, 1), active_days=act_days,
                last_age_h=round((d["fetched"] - d["newest"]) / 3600, 1) if d["newest"] else None,
                train=window_stats(tr, max(0.5, (split - start) / 86400)), test=window_stats(te, max(0.5, (d["fetched"] - split) / 86400)))

def load_all(pattern=os.path.join(HERE, "trades", "*.json")):
    return [json.load(open(f)) for f in glob.glob(pattern)]
