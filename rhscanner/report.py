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


def format_paper(hours: float | None, s: dict, recent: list[tuple[str, dict]], trained_until: float | None) -> str:
    """/karne: the paper test (nothing is bought). `recent`: (symbol, alert row)."""
    span = f"son {hours:g} saat" if hours else "başından beri"
    lines = [f"🧪 <b>Kâğıt test</b> — {span} (para harcanmaz)",
             "Fomo'da 5. alıcıya ulaşan her yeni coin puanlanır; en iyi %2 seçilir. Her seçim için sanal işlem: "
             "30 sn sonra alış, 2x'te yarısı satılır, kalan zirveden %50 düşünce, %50 zarar-kes; komisyon ve kayma dahil.",
             "",
             f"Puanlanan coin: {s['scored']} · seçilen: <b>{s['alerts']}</b> · kapanan işlem: {s['closed']}",
             f"2x yapan: {s['x2']} · zarar-kese takılan: {s['stop']}"]
    if s["mean"] is not None:
        lines.append(f"İşlem başına net: ort <b>{_pct(s['mean'])}</b> · medyan {_pct(s['median'])} · "
                     f"kârlı %{100 * s['win']:.0f}")
    lines.append(f"Sanal kasa ($1.000, kasanın %4/%2/%1'i): <b>${s['bank']:,.0f}</b> "
                 f"({s['bank'] / 1000:.2f}x; açık işlemler son fiyatla)")
    if s["latency"] is not None:
        lines.append(f"Seçim gecikmesi (5. alıcıdan sonra, medyan): {s['latency']:.0f} sn")
    if recent:
        lines += ["", "Son seçimler:"]
        for symbol, r in recent:
            state = {"2x": "2x ✅", "stop": "zarar-kes ❌", "yok": "bekliyor"}.get(r["kind"] or "", "giriş bekliyor")
            res = f" · net {_pct(r['ret'])}{'' if r['closed'] else ' (açık)'}" if r["ret"] is not None else ""
            when = time.strftime("%d.%m %H:%M", time.gmtime(r["ts"]))
            lines.append(f"• {escape(symbol, quote=False)} ({when} UTC) — {state}{res}")
    if trained_until:
        lines.append(f"\n<i>Model {time.strftime('%d.%m', time.gmtime(trained_until))} tarihine kadarki veriyle eğitildi.</i>")
    return "\n".join(lines)


def format_paper_alert(symbol: str, token: str, price: float, score: float, size: float | None, delay: float) -> str:
    """Optional message for each paper-test pick (/kagitbildirim ac)."""
    return (f"🧪 <b>Kâğıt test seçimi: {escape(symbol, quote=False)}</b>\n"
            f"Puan {score:.3f} (en iyi %2) · sanal tutar kasanın %{100 * (size or 0):.0f}'i\n"
            f"Bildirim fiyatı: {price:.3g} $/birim · 5. alıcıdan {delay:.0f} sn sonra\n"
            f"<code>{token}</code>\n"
            f"<i>Sadece test: gerçek alım önerisi değildir.</i>")
