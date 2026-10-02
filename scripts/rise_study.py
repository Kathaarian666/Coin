"""Rise criteria study (PROJE.md step 2): which facts known at the alert moment raise the chance of a 2x?

  python scripts/rise_study.py <winners.parquet> <security.parquet> [k=3] [<first test day>=2026-09-26]

Label (PROJE.md §1): two buys in a row at >= 2x the moment's price, any time (winner_study `t2x_h`). Coins need
OBS_MIN hours of data after the moment so "never" means never (rule 7, PROJE.md §6). Train = before CUT,
test = from CUT on (days no criterion was chosen on).
1. moments: 3rd / 5th / 10th distinct Fomo buyer: coins per day, 2x rate, minutes after the first Fomo trade.
2. single criteria at moment k: 2x rate in the bottom and top fifth (cut points from the train days), train and
   test side by side. güçlü / orta = same direction in test with at least half the train gap and >= 10 / 5
   points; etkisiz = under 5 points even on the train days; tutmuyor = the test days disagree.
3. all criteria together (reference): gradient boosting retrained every day on the days before it (walk-forward);
   only labels known when the day began; the day's score bars come from the model's scores on the 2 days before.
   Per bar: alerts per day, their 2x rate with a 95% margin, and the worst / best test day.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

OBS_MIN = 24.0
CUT = pd.Timestamp("2026-09-26").value / 1e9
DAY = 86400

# name shown to the user, column; holder columns come from scripts/security_extra.py (moment k=3 only)
CRITERIA = {
    "3. alıcıya kadar geçen dakika": "mins_to_k",
    "İşlem sayısı (o ana kadar)": "trades_to_k",
    "Toplam alım $": "usd_all",
    "İşlem başına alım $": "usd_per_trade",
    "En büyük tek alım $": "max_buy",
    "En büyük alıcının payı": "top_buyer_share",
    "Tekrar alım oranı": "repeat_buys",
    "Satıcı sayısı": "sellers",
    "İlk alıcılardan satanların oranı": "early_sold",
    "Satış $ payı": "sell_usd_share",
    "Son 5 dk alıcı": "buyers_5m",
    "Son 10 dk alım $": "usd_10m",
    "Yeni cüzdan oranı": "fresh_share",
    "Akıllı cüzdan sayısı": "smart",
    "İlk alımdan bu yana fiyat (x)": "runup",
    "Zirveden uzaklık": "off_high",
    "Piyasa değeri (FDV $)": "fdv",
    "Lansmandan bu yana dakika": "launch_age_min",
    "Geliştiricinin önceki coin sayısı": "launcher_prior",
    "Fomo'da son 1 saat alıcı (piyasa)": "market_buyers_1h",
    "Saat (UTC)": "hour",
    "İlk 10 cüzdan payı %": "top10_pct",
    "En büyük cüzdan payı %": "largest_pct",
    "Geliştirici payı %": "dev_pct",
    "Sniper payı %": "sniper_pct",
    "Havuz derinliği $": "depth_usd",
    # angle D (PROJE.md §4.4)
    "Son 60 sn alıcı": "buyers_60s",
    "Son 60 sn alım payı": "usd_60s_share",
    "Aynı blokta alım (bot)": "same_block_buys",
    "Küçük alım (<$20) payı": "small_buy_share",
    "Geliştiricinin önceki coinlerinde 1 saatte 2x oranı": "launcher_hit_rate",
    "İlk 3 alıcının geçmiş 1 saatte 2x oranı": "buyers_hit_rate",
}


# chosen with the user on 2 Oct (PROJE.md §1): the "güçlü" / "orta" criteria; the model uses only these
DROPPED = {"launcher_prior", "dev_pct", "smart", "hour", "sniper_pct", "fresh_share", "repeat_buys", "top_buyer_share",
           "market_buyers_1h"}
CHOSEN = [c for c in CRITERIA.values() if c not in DROPPED]


def add_history(w):
    """Track records known at each moment: the launcher's earlier coins and the first 3 buyers' earlier first buys.
    Outcome = 2x within 1 h of that coin's moment, so it is known 1 h later (no look-ahead)."""
    w = w.sort_values("ts")
    hit = (w.t2x_h.fillna(99) <= 1).values
    pending, l_hist, b_hist = [], {}, {}
    l_rate, b_rate = [], []
    events = list(zip(w.ts.values, w.launcher.fillna("").values, w.first3.fillna("").values, hit))
    import heapq
    for t, launcher, first3, h in events:
        while pending and pending[0][0] <= t:
            _, kind, key, outcome = heapq.heappop(pending)
            book = l_hist if kind == "l" else b_hist
            n, k = book.get(key, (0, 0))
            book[key] = (n + 1, k + outcome)
        n, k = l_hist.get(launcher, (0, 0)) if launcher else (0, 0)
        l_rate.append(k / n if n else np.nan)
        wallets = [x for x in first3.split(",") if x]
        tot = [b_hist.get(x, (0, 0)) for x in wallets]
        n = sum(a for a, _ in tot)
        b_rate.append(sum(b for _, b in tot) / n if n >= 3 else np.nan)
        if launcher:
            heapq.heappush(pending, (t + 3600, "l", launcher, int(h)))
        for x in wallets:
            heapq.heappush(pending, (t + 3600, "b", x, int(h)))
    return w.assign(launcher_hit_rate=l_rate, buyers_hit_rate=b_rate)


def load(winners, security, k):
    w = pd.read_parquet(winners)
    w = w[w.k == k].copy()
    if "first3" in w:
        w = add_history(w)
    w["hit2x"] = w.t2x_h.notna()
    w["hour"] = (w.ts % DAY) // 3600
    w["day"] = (w.ts // DAY).astype(int)
    if k == 3 and security and Path(security).exists():  # holder columns: scripts/security_extra.py
        cols = ["token", "top10_pct", "largest_pct", "dev_pct", "sniper_pct"]
        s = pd.read_parquet(security)
        s = s[[c for c in cols if c in s]].rename(columns={"token": "coin"})
        w = w.merge(s, on="coin", how="left")
    return w[w.obs_h >= OBS_MIN]


def moments(winners):
    w = pd.read_parquet(winners)
    print(f"1) Bildirim anı (en az {OBS_MIN:.0f} saat izlenmiş coinler)")
    print(f"{'an':>10} {'coin':>6} {'günde':>6} {'2x':>6} {'ilk Fomo işleminden dk (medyan)':>32}")
    days = (w.ts.max() - w.ts.min()) / DAY
    for k, g in w[w.obs_h >= OBS_MIN].groupby("k"):
        if k > 10:
            continue
        print(f"{str(k) + '. alıcı':>10} {len(g):6d} {len(g) / days:6.0f} {100 * g.t2x_h.notna().mean():5.1f}% "
              f"{g.mins_to_k.median():32.1f}")
    late = w[(w.k == 3) & w.t2x_h.notna()].t2x_h
    print(f"2x'e ulaşma süresi (3. alıcı): medyan {late.median() * 60:.0f} dk · ilk 1 saatte %{100 * (late <= 1).mean():.0f} · "
          f"24 saatten sonra %{100 * (late > 24).mean():.1f}\n")


def single(df):
    tr, te = df[df.ts < CUT], df[df.ts >= CUT]
    print(f"2) Kriterler tek tek: 2x oranı, en düşük / en yüksek beşte birlik dilim (eğitim {len(tr)} coin, "
          f"test {len(te)} coin; taban eğitim %{100 * tr.hit2x.mean():.0f}, test %{100 * te.hit2x.mean():.0f})")
    print(f"{'kriter':36} {'eğitim alt/üst':>15} {'test alt/üst':>14}  sonuç")
    rows = []
    for name, col in CRITERIA.items():
        if col not in df or df[col].notna().sum() < 500:
            continue
        q = tr[col].dropna().quantile([0.2, 0.8]).values
        if q[0] == q[1]:
            continue
        r = []
        for part in (tr, te):
            x = part[part[col].notna()]
            r += [x[x[col] <= q[0]].hit2x.mean(), x[x[col] >= q[1]].hit2x.mean()]
        gap_tr, gap_te = r[1] - r[0], r[3] - r[2]
        holds = np.sign(gap_tr) == np.sign(gap_te) and abs(gap_te) >= abs(gap_tr) / 2
        if abs(gap_tr) < 0.05:
            verdict = "etkisiz"  # under 5 points apart even on the days it was measured on
        elif not holds:
            verdict = "tutmuyor"
        else:
            verdict = "güçlü" if abs(gap_te) >= 0.10 else "orta"
        rows.append((abs(gap_te) if holds and verdict != "etkisiz" else -1 + abs(gap_tr), name, r, verdict))
    for _, name, r, verdict in sorted(rows, key=lambda x: -x[0]):
        print(f"{name:36} {100 * r[0]:6.0f}%/{100 * r[1]:3.0f}% {100 * r[2]:6.0f}%/{100 * r[3]:3.0f}%  {verdict}")
    print()


def together(df):
    cols = [c for c in CHOSEN if c in df]
    first_test = int(CUT // DAY)
    out, past_p = [], []
    for d in sorted(df.day.unique()):
        if d < first_test:
            continue
        start = d * DAY
        # only what was known when day d began: coins at least 6 h old, 2x counted only if it happened before then
        tr = df[df.ts < start - 6 * 3600]
        y = tr.t2x_h.notna() & (tr.ts + 3600 * tr.t2x_h.fillna(0) < start)
        te = df[df.day == d]
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
                                           random_state=0).fit(tr[cols], y)
        p = m.predict_proba(te[cols])[:, 1]
        # the day's bars: the model's own scores on the 2 days before (out of sample once there are any)
        ref = np.concatenate(past_p[-2:]) if past_p else m.predict_proba(tr[tr.day >= d - 2][cols])[:, 1]
        out.append(te.assign(p=p, pct=np.searchsorted(np.sort(ref), p) / len(ref)))
        past_p.append(p)
    res = pd.concat(out)
    n_days = res.day.nunique()
    print(f"3) Hepsi birlikte (referans): her gün önceki günlerle eğitilen model, {n_days} test günü, {len(res)} coin")
    print(f"{'seçim':>16} {'günde bildirim':>15} {'2x':>6} {'hata payı':>10} {'gün gün 2x en düşük-en yüksek':>31}")
    for top in (1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01):
        sel = res[res.pct >= 1 - top]
        if len(sel) < 5:
            continue
        rate = sel.hit2x.mean()
        per_day = sel.groupby("day").hit2x.mean()
        print(f"{'en iyi %' + format(100 * top, 'g'):>16} {len(sel) / n_days:15.1f} {100 * rate:5.1f}% "
              f"{'±' + format(196 * np.sqrt(rate * (1 - rate) / len(sel)), '.0f'):>10} "
              f"{100 * per_day.min():22.0f}%-{100 * per_day.max():.0f}%")
    return res


def main():
    winners, security = sys.argv[1], sys.argv[2]
    global CUT
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    if len(sys.argv) > 4:
        CUT = pd.Timestamp(sys.argv[4]).value / 1e9
    moments(winners)
    df = load(winners, security, k)
    single(df)
    together(df)


if __name__ == "__main__":
    main()
