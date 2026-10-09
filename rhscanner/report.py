"""Formats a report as a Telegram HTML message (Turkish)."""

import time
from html import escape

from .config import DEXSCREENER_CHAIN
from .scoring import level

ICONS = {"critical": "⛔", "high": "🔴", "medium": "🟠", "low": "🟡", "info": "ℹ️", "good": "✅"}
ORDER = ["critical", "high", "medium", "low", "good", "info"]


def _usd(value) -> str:
    if value in (None, ""):
        return "?"
    value = float(value)
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def format_report(report: dict, blockscout_url: str, header: str = "") -> str:
    icon, label = level(report["score"])
    token = report["token"]
    pool = report.get("pool") or {}
    header = f"<b>{escape(header, quote=False)}</b>\n" if header else ""
    lines = [
        f"{header}<b>{escape(str(report.get('name')))}</b> (${escape(str(report.get('symbol')))})",
        f"<code>{token}</code>",
        "",
        f"{icon} <b>Güven skoru: {report['score']}/100</b> — {label}",
    ]
    if report.get("missing"):
        lines.append(f"⚠️ Kontrol edilemeyenler: {escape(', '.join(report['missing']), quote=False)} (skor en fazla 70)")

    facts = []
    fomo = report.get("fomo") or {}
    if fomo.get("buyers"):
        facts.append(
            f"📱 Fomo (son {fomo['window_min']:g} dk): {fomo['buyers']} alıcı / {fomo['sellers']} satıcı · "
            f"alım {_usd(fomo['buy_usd'])} / satış {_usd(fomo['sell_usd'])}"
        )
    hp = report.get("honeypot") or {}
    if hp.get("simulated") and "buy_tax" in hp:
        facts.append(f"Vergi: alım %{hp['buy_tax']:.1f} / satış %{hp['sell_tax']:.1f}")
    liq = report.get("liquidity") or {}
    if "liquidity_eth" in liq:
        facts.append(f"Likidite: {liq['liquidity_eth']:.2f} ETH")
    holders = report.get("holders") or {}
    if "top10_pct" in holders:
        facts.append(f"İlk 10 cüzdan: %{holders['top10_pct']:.1f}")
    market = report.get("market") or {}
    if market.get("fdv"):
        facts.append(f"FDV: {_usd(market['fdv'])} · Likidite: {_usd(market.get('liquidity_usd'))}")
    if market.get("buys_h1") is not None:
        facts.append(f"1s: {market['buys_h1']} alım / {market['sells_h1']} satış")
    launch = report.get("launch") or {}
    if launch:
        parts = []
        if launch.get("age_min") is not None:
            age = launch["age_min"]
            parts.append(f"Yaş: {age:.0f} dk" if age < 120 else f"Yaş: {age / 60:.1f} sa" if age < 2880 else f"Yaş: {age / 1440:.0f} gün")
        if launch.get("dev_pct") is not None:
            parts.append(f"Dev: %{launch['dev_pct']:.1f} (lansmanda %{launch.get('dev_initial_pct', 0):.1f})")
        if launch.get("sniper_pct") is not None:
            parts.append(f"Sniper: %{launch['sniper_pct']:.1f}")
        if launch.get("bundle_pct"):
            parts.append(f"Bundle: %{launch['bundle_pct']:.1f}")
        if parts:
            facts.append(" · ".join(parts))
    deployer = report.get("deployer") or {}
    prev = deployer.get("previous_launches")
    if prev is not None and (prev or not deployer.get("partial")):
        more = "+" if deployer.get("partial") else ""  # some history windows failed: a lower bound
        text = f"Geliştirici: {prev}{more} önceki coin" if prev else "Geliştirici: ilk coini"
        if prev and deployer.get("checked"):
            text += f", son {deployer['checked']} coinden {deployer['alive']} tanesi yaşıyor"
        if deployer.get("best_previous_fdv", 0) >= 100_000:
            text += f" · en iyisi {_usd(deployer['best_previous_fdv'])} FDV"
        facts.append(text)
    wash = report.get("wash") or {}
    if wash.get("transfers_5m"):
        facts.append(f"Son 5 dk: {wash['transfers_5m']} transfer, {wash['wallets_5m']} cüzdan")
    if pool:
        launchpad = (report.get("liquidity") or {}).get("launchpad")
        pair = f" · {pool['quote_symbol']} paritesi" if pool.get("quote_symbol") else ""
        facts.append(f"Havuz: Uniswap {pool.get('dex', '?').upper()}{pair}" + (f" · {launchpad}" if launchpad else ""))
    if facts:
        lines += [""] + [f"• {escape(f, quote=False)}" for f in facts]

    findings = sorted(report.get("findings", []), key=lambda f: ORDER.index(f["severity"]))
    shown = [f for f in findings if f["severity"] != "info"][:12]
    if shown:
        lines.append("")
        lines += [f"{ICONS[f['severity']]} {escape(f['message'], quote=False)}" for f in shown]

    links = [f'<a href="{blockscout_url}/token/{token}">Explorer</a>']
    links.append(f'<a href="https://dexscreener.com/{DEXSCREENER_CHAIN}/{token}">DexScreener</a>')
    lines += ["", " · ".join(links)]
    lines.append("<i>Yatırım tavsiyesi değildir. Otomatik kontroller her riski yakalayamaz.</i>")
    return "\n".join(lines)


def _money(value) -> str:
    return "–" if value is None else f"{value:+.1f}$"


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:+.0f}%"


def format_paper(hours: float | None, s: dict, recent: list[tuple[str, dict]], trained_until: float | None,
                 other: dict | None = None) -> str:
    """/karne: the paper test (nothing is bought). `recent`: (symbol, alert row); `other`: the summary of the second
    model (+ holder criteria, PROJE.md §4.6) run beside it. The sell rule is the 5x rule since 9 Oct (PROJE.md §0 B1);
    the old rule stays beside it for comparison."""
    span = f"son {hours:g} saat" if hours else "başından beri"
    lines = [f"🧪 <b>Kâğıt test</b> — {span} (para harcanmaz)",
             "Fomo'da 5. alıcıya ulaşan her yeni coin puanlanır; en iyi %2 seçilir. Her seçim için sanal işlem: "
             "30 sn sonra alış; komisyon ve kayma dahil.",
             f"Puanlanan coin: {s['scored']} · seçilen: <b>{s['alerts']}</b>"
             + (f" · seçim gecikmesi (medyan) {s['latency']:.0f} sn" if s["latency"] is not None else ""),
             "",
             "🎯 <b>Satış kuralı: 5x</b> (5x'te hepsi satılır, gelmezse 3 saatte kalanı; o anda havuzun likiditesi "
             "çekilmişse değer 0):",
             f"5x yapan: <b>{s['x5']}</b> · 3 saatte satılan: {s['time5']} (likiditesi çekilmiş: {s['pulled5']})",
             f"Sanal kasa ($1.000, kasanın %4/%2/%1'i): <b>${s['bank5']:,.0f}</b> ({s['bank5'] / 1000:.2f}x)",
             "",
             "Eski kural, karşılaştırma için (2x'te yarısı, kalan zirveden %50 düşünce, %50 zarar-kes; açık işlemler son "
             "fiyatla, iyimser):",
             f"2x yapan: {s['x2']} · zarar-kese takılan: {s['stop']} · kapanan: {s['closed']}"]
    if s["mean"] is not None:
        lines.append(f"İşlem başına net: ort {_pct(s['mean'])} · medyan {_pct(s['median'])} · kârlı %{100 * s['win']:.0f}")
    lines.append(f"Sanal kasa: ${s['bank']:,.0f} ({s['bank'] / 1000:.2f}x)")
    if recent:
        lines += ["", "Son seçimler (5x kuralı · eski kural):"]
        for symbol, r in recent:
            state = {"2x": "2x ✅", "stop": "zarar-kes ❌", "yok": "bekliyor"}.get(r["kind"] or "", "giriş bekliyor")
            res = f" {_pct(r['ret'])}{'' if r['closed'] else ' (açık)'}" if r["ret"] is not None else ""
            when = time.strftime("%d.%m %H:%M", time.gmtime(r["ts"]))
            k5 = r.get("kind5")
            rule5 = {"5x": "5x ✅", "süre": "3 sa" + (" (likidite çekilmiş ❌)" if r.get("chain5") == "çekildi" else "")
                     }.get(k5 or "", "bekliyor")
            res5 = f" <b>{_pct(r['ret5'])}</b>" if r.get("ret5") is not None else ""
            lines.append(f"• {escape(symbol, quote=False)} ({when} UTC) — {rule5}{res5} · eski: {state}{res}")
    if other is not None:
        lines += ["", "🧪 <b>İkinci model (+ holder kriterleri)</b>, aynı coinler, kendi en iyi %2'si:",
                  f"Puanlanan: {other['scored']} · seçilen: <b>{other['alerts']}</b> · 5x yapan: {other['x5']}",
                  f"Sanal kasa, 5x kuralı: <b>${other['bank5']:,.0f}</b> ({other['bank5'] / 1000:.2f}x) · eski kural: "
                  f"${other['bank']:,.0f} ({other['bank'] / 1000:.2f}x)"]
    if trained_until:
        lines.append(f"\n<i>Model {time.strftime('%d.%m', time.gmtime(trained_until))} tarihine kadarki veriyle eğitildi.</i>")
    return "\n".join(lines)


def _mcap(fdv: float | None) -> str:
    """The alert's level as Fomo shows it: market cap (price x supply), not the price of a raw unit (PROJE.md §0 D3)."""
    if fdv is None or fdv != fdv or fdv <= 0:
        return "Piyasa değeri: bilinmiyor (arz okunamadı)"
    return f"Piyasa değeri (bildirimde): <b>{_usd(fdv)}</b> · 5x satış hedefi: {_usd(5 * fdv)}"


def format_paper_5x(symbol: str, token: str, minutes: float) -> str:
    """The paper test's 5x rule hit (/kagitbildirim ac): the moment to sell everything (PROJE.md §4.4c)."""
    return (f"🎯 <b>{escape(symbol, quote=False)}</b> kâğıt testte bildirim fiyatının <b>5 katına</b> ulaştı "
            f"({minutes:.0f} dk sonra). 5x kuralına göre şimdi hepsi satılır — gecikme pahalı: 15 dk sonra seçimlerin "
            f"bir kısmında likidite çekilmiş oluyor.\n<code>{token}</code> · {_gecko(token)}")


def format_paper_alert(symbol: str, token: str, fdv: float | None, score: float, size: float | None, delay: float) -> str:
    """Optional message for each paper-test pick (/kagitbildirim ac)."""
    return (f"🧪 <b>Kâğıt test seçimi: {escape(symbol, quote=False)}</b>\n"
            f"Puan {score:.3f} (en iyi %2) · sanal tutar kasanın %{100 * (size or 0):.0f}'i\n"
            f"{_mcap(fdv)} · 5. alıcıdan {delay:.0f} sn sonra\n"
            f"<code>{token}</code>\n"
            f"<i>Sadece test: gerçek alım önerisi değildir.</i>")


def _gecko(token: str) -> str:
    return f'<a href="https://www.geckoterminal.com/robinhood/tokens/{token}">GeckoTerminal</a>'


def format_live_alert(symbol: str, token: str, fdv: float | None, chance: float | None, reasons: list[tuple[str, str]],
                      gate: tuple[str, str], delay: float) -> str:
    """The fast message of a real alert (/canli ac); the safety report follows as a reply."""
    status, detail = gate
    gate_line = ("✅ " if status == "ok" else "⚠️ Satılabilirlik doğrulanamadı: ") + escape(detail, quote=False)
    lines = [f"🚀 <b>{escape(symbol, quote=False)}</b> — yeni coin, Fomo'da 5. alıcı",
             f"2x ihtimali: <b>~%{100 * chance:.0f}</b> (geçmişte bu seviyedeki seçimler)" if chance else
             "2x ihtimali: en iyi %2",
             "Neden seçildi:"]
    lines += [f"• {escape(name, quote=False)}: {escape(value, quote=False)}" for name, value in reasons] or ["• -"]
    lines += [gate_line,
              f"{_mcap(fdv)} · 5. alıcıdan {delay:.0f} sn sonra",
              f"<code>{token}</code> · {_gecko(token)}",
              "Satış kuralı: 5x'te hepsi, 3 saatte gelmezse kalanı sat (bot haber verir).",
              "<i>Güven raporu birazdan bu mesaja yanıt olarak gelecek. Karar senin.</i>"]
    return "\n".join(lines)


SAFETY_ICONS = {"ok": "✅", "warn": "⚠️", "unknown": "❔"}


def format_safety(symbol: str, token: str, trust: int | None, items: list[tuple[str, str, str]],
                  sources: list[tuple[str, bool]]) -> str:
    """The safety report (PROJE.md §1): one trust score (the model) and the 14 checks in a fixed order."""
    if trust is None:
        head = "🛡 <b>Güven puanı: bilinmiyor</b>"
    else:
        word = "yüksek" if trust >= 85 else "orta" if trust >= 70 else "düşük"
        head = f"🛡 <b>Güven puanı: {trust}/100</b> ({word})"
    lines = [f"{head} — {escape(symbol, quote=False)}",
             "<i>Geçmişte bu işaretlere sahip coinlerin tuzak (rug / satılamama) oranından hesaplanır.</i>", ""]
    lines += [f"{SAFETY_ICONS.get(st, '❔')} {escape(name, quote=False)}: {escape(text, quote=False)}"
              for name, st, text in items]
    src = " · ".join(f"{escape(n, quote=False)} {'✓' if ok else '–'}" for n, ok in sources)
    lines += ["", f"Kaynaklar: {src} (– = bu coin için henüz bilgisi yok)",
              f"<code>{token}</code> · {_gecko(token)} · "
              f'<a href="https://dexscreener.com/{DEXSCREENER_CHAIN}/{token}">DexScreener</a>',
              "<i>Hiçbiri eleme yapmaz; satılamayan coinler bildirimden önce elenir. Yatırım tavsiyesi değildir.</i>"]
    return "\n".join(lines)


def format_5x(symbol: str, token: str, minutes: float) -> str:
    """The 5x rule's target (PROJE.md §4.4c, user 9 Oct): the moment to sell everything."""
    return (f"🎯 <b>{escape(symbol, quote=False)}</b> bildirimdeki piyasa değerinin <b>5 katına</b> ulaştı "
            f"({minutes:.0f} dk sonra). 5x kuralı: <b>şimdi hepsini sat</b> — gecikme pahalı (15 dk sonra seçimlerin bir "
            f"kısmında likidite çekilmiş oluyor). Karar senin.\n<code>{token}</code> · {_gecko(token)}")


def format_time_up(symbol: str, token: str, hours: float) -> str:
    """The 5x rule's time limit without the target: sell what is left."""
    return (f"⏱ <b>{escape(symbol, quote=False)}</b>: {hours:g} saat doldu, 5x gelmedi. 5x kuralı: <b>kalanı sat</b> "
            f"(bekleyen seçimlerin çoğu sonradan düşüyor ya da likiditesi çekiliyor). Karar senin.\n"
            f"<code>{token}</code> · {_gecko(token)}")


def format_liquidity_warning(symbol: str, token: str, pulled_pct: float) -> str:
    return (f"⚠️ <b>{escape(symbol, quote=False)}</b>: havuzdaki likiditenin %{pulled_pct:.0f}'i çekildi. "
            f"Rug olabilir, dikkat.\n<code>{token}</code> · {_gecko(token)}")
