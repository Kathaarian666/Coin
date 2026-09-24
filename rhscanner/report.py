"""Formats a report as a Telegram HTML message (Turkish)."""

from html import escape

from .config import DEXSCREENER_CHAIN
from .momentum import momentum_label
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
    momentum = report.get("momentum") or {}
    if momentum.get("score") is not None:
        m_icon, m_label = momentum_label(momentum["score"])
        lines.append(f"{m_icon} <b>Momentum: {momentum['score']}/100</b> — {m_label}")
        for reason in (momentum.get("reasons") or [])[:3]:
            lines.append(f"   · {escape(reason, quote=False)}")

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


def _pct_change(old, new) -> float | None:
    try:
        old, new = float(old), float(new)
    except (TypeError, ValueError):
        return None
    return None if old <= 0 else 100.0 * (new - old) / old


def format_followup(report: dict, recent: dict, sellers_hour: int, market: dict, minutes: float) -> str:
    """Short update on a token some minutes after its alert."""
    token = report["token"]
    then = report.get("market") or {}
    lines = [
        f"🔁 <b>Takip · {escape(str(report.get('name')), quote=False)}</b> "
        f"(${escape(str(report.get('symbol')), quote=False)}) — {minutes:g} dk sonra",
        f"<code>{token}</code>",
        "",
    ]

    price = _pct_change(then.get("price_usd"), market.get("price_usd"))
    if price is not None:
        icon = "📈" if price >= 0 else "📉"
        lines.append(f"{icon} Fiyat bildirimden beri: {price:+.1f}%")
    liquidity = _pct_change(then.get("liquidity_usd"), market.get("liquidity_usd"))
    if liquidity is not None:
        lines.append(f"💧 Likidite: {_usd(then.get('liquidity_usd'))} → {_usd(market.get('liquidity_usd'))} ({liquidity:+.0f}%)")
        if liquidity <= -50:
            lines.append("🚨 <b>Likidite yarıdan fazla düştü — rugpull olabilir!</b>")

    lines.append(
        f"📱 Fomo (son {minutes:g} dk): {recent['buyers']} alıcı / {recent['sellers']} satıcı · "
        f"alım {_usd(recent['buy_usd'])} / satış {_usd(recent['sell_usd'])}"
    )
    if sellers_hour >= 2:
        lines.append(f"✅ Satış doğrulandı: son 1 saatte {sellers_hour} farklı Fomo kullanıcısı sattı")
    elif sellers_hour == 1:
        lines.append("🟡 Son 1 saatte sadece 1 Fomo kullanıcısı satabildi")
    else:
        lines.append("⚠️ <b>Hâlâ hiç Fomo satışı yok</b> — satılamıyor olabilir, dikkat!")
    if recent["sell_usd"] >= 1000 and recent["sell_usd"] > 2 * recent["buy_usd"]:
        lines.append("🔴 Satış baskısı: satışlar alımların 2 katından fazla")
    elif recent["buyers"] == 0:
        lines.append("💤 Fomo'da yeni alıcı gelmiyor, ilgi söndü")

    lines += ["", f'<a href="https://dexscreener.com/{DEXSCREENER_CHAIN}/{token}">DexScreener</a>']
    return "\n".join(lines)


def format_scorecard(hours: float, groups: list[tuple[str, dict]]) -> str:
    """/karne: how signals did, by kind and by momentum bucket."""
    lines = [f"📊 <b>Sinyal karnesi — son {hours:g} saat</b>", "<i>(en az 1 saatlik sinyaller)</i>", ""]
    for title, s in groups:
        if not s.get("n"):
            lines.append(f"<b>{escape(title, quote=False)}</b>: veri yok")
            continue
        lines.append(
            f"<b>{escape(title, quote=False)}</b> ({s['n']} sinyal)\n"
            f"   1 saatte 2x: %{s['x2_60']} · 1.5x: %{s['up50_60']} · 24s içinde 2x: %{s['x2_all']} · 5x: %{s['x5_all']}\n"
            f"   1 saatte yarıya düşen: %{s['down50_60']} · rug: %{s['rugged']}\n"
            f"   medyan 1s zirvesi: {s['median_max60']}x · medyan 1s sonu: {s['median_ret60']}x"
        )
    lines += ["", "<i>Gölge = eşiğin yarısını geçen, analiz edilmemiş coinler (karşılaştırma grubu).</i>"]
    return "\n".join(lines)
