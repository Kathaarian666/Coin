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
    fees = report.get("fees") or {}
    if fees.get("breakeven"):
        lines.append(f"💸 ${fees['position']:g} pozisyonda komisyonla başa baş: <b>{fees['breakeven']:.2f}x</b>")

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


def _pct_change(old, new) -> float | None:
    try:
        old, new = float(old), float(new)
    except (TypeError, ValueError):
        return None
    return None if old <= 0 else 100.0 * (new - old) / old


def format_followup(report: dict, recent: dict, sellers_hour: int, market: dict, minutes: float,
                    exit_reasons: list | None = None) -> str:
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

    if exit_reasons:
        lines += [f"⚠️ {escape(reason, quote=False)}" for _, reason in exit_reasons]
    elif price is not None and price <= -30:
        lines.append(
            "🟢 Düşüş var ama çıkış sinyali yok: dev ve büyük cüzdanlar satmadı, likidite yerinde, "
            "Fomo'da satış dalgası yok — sağlıklı geri çekilme olabilir"
        )

    lines += ["", f'<a href="https://dexscreener.com/{DEXSCREENER_CHAIN}/{token}">DexScreener</a>']
    return "\n".join(lines)


def format_exit(report: dict, reasons: list, level: str, market: dict, minutes: float) -> str:
    """🔴 ÇIK / 🟠 DİKKAT message for an alerted token."""
    token = report["token"]
    title = "🔴 <b>ÇIK sinyali</b>" if level == "strong" else "🟠 <b>DİKKAT</b>"
    lines = [
        f"{title} · <b>{escape(str(report.get('name')), quote=False)}</b> "
        f"(${escape(str(report.get('symbol')), quote=False)}) — bildirimden {minutes:g} dk sonra",
        f"<code>{token}</code>",
        "",
    ]
    lines += [f"• {escape(reason, quote=False)}" for _, reason in reasons]
    price = _pct_change((report.get("market") or {}).get("price_usd"), market.get("price_usd"))
    if price is not None:
        lines.append(f"{'📈' if price >= 0 else '📉'} Fiyat bildirimden beri: {price:+.1f}%")
    lines += ["", f'<a href="https://dexscreener.com/{DEXSCREENER_CHAIN}/{token}">DexScreener</a>']
    return "\n".join(lines)


TELEGRAM_CHUNK = 3500  # Telegram refuses messages over 4096 characters


def _chunks(blocks: list[str], limit: int = TELEGRAM_CHUNK) -> list[str]:
    """Join blocks into as few messages as fit under the limit, never splitting a block."""
    messages, current = [], ""
    for block in blocks:
        if current and len(current) + 1 + len(block) > limit:
            messages.append(current)
            current = block
        else:
            current = f"{current}\n{block}" if current else block
    return messages + ([current] if current else [])


KIND_NAMES = {"alert": "bildirim", "filtered": "filtre", "shadow": "gölge", "wave2": "ikinci dalga",
              "exit": "ÇIK", "caution": "DİKKAT"}


def format_scorecard(hours: float, groups: list[tuple[str, dict]],
                     exits: list[tuple[str, dict]] | None = None, unmeasured: dict[str, int] | None = None) -> list[str]:
    """/karne: how signals did, by kind and bucket; one or more Telegram messages."""
    blocks = [f"📊 <b>Sinyal karnesi — son {hours:g} saat</b>\n<i>(en az 1 saatlik sinyaller)</i>\n"]
    missing = {k: n for k, n in (unmeasured or {}).items() if k in KIND_NAMES and n}
    if missing:
        blocks.append("⚠️ <i>Sinyal anında fiyatı alınamadığı için ölçülemeyen: "
                      + ", ".join(f"{KIND_NAMES[k]} {n}" for k, n in missing.items()) + "</i>\n")
    for title, s in groups:
        if not s.get("n"):
            blocks.append(f"<b>{escape(title, quote=False)}</b>: veri yok")
            continue
        blocks.append(
            f"<b>{escape(title, quote=False)}</b> ({s['n']} sinyal)\n"
            f"   1 saatte 2x: %{s['x2_60']} · 1.5x: %{s['up50_60']} · 24s içinde 2x: %{s['x2_all']} · 5x: %{s['x5_all']}\n"
            f"   1 saatte yarıya düşen: %{s['down50_60']} · rug: %{s['rugged']}\n"
            f"   medyan 1s zirvesi: {s['median_max60']}x · medyan 1s sonu: {s['median_ret60']}x"
        )
    if exits:
        blocks.append("\n🚪 <b>Çıkış sinyalleri</b> <i>(fiyat sinyalin gönderildiği andan itibaren)</i>")
        for title, s in exits:
            if not s.get("n"):
                blocks.append(f"<b>{escape(title, quote=False)}</b>: veri yok")
                continue
            blocks.append(
                f"<b>{escape(title, quote=False)}</b> ({s['n']} sinyal)\n"
                f"   ✅ 1 saat sonra daha aşağıda: %{s['lower_60']} · %20+ düşen: %{s['down20_60']} · rug: %{s['rugged']}\n"
                f"   ❌ sonra 1.5x olan (kaçırılan): %{s['up50_60']} · 24s içinde 2x: %{s['x2_all']}\n"
                f"   medyan 1s sonu: {s['median_ret60']}x"
            )
    blocks.append("\n<i>Gölge = eşiğin yarısını geçen, analiz edilmemiş coinler (karşılaştırma grubu).</i>")
    return _chunks(blocks)


def format_findings(hours: float, overall: dict, rows: list[tuple[str, dict]], pons: bool = False) -> str:
    """/bulgular: how analysed signals did, split by the findings that lowered their trust score
    (pons=True: early Pons signals, split by the junk filter's reasons)."""
    scope = "erken Pons sinyalleri, çöp nedenlerine göre" if pons else "analiz edilen sinyaller: bildirim + filtre"
    lines = [f"🔎 <b>Bulgulara göre sonuçlar — son {hours:g} saat</b>", f"<i>({scope})</i>", ""]
    if not overall.get("n"):
        return "\n".join(lines + ["Veri yok."])
    lines.append(f"<b>Hepsi</b> ({overall['n']}): 1s 2x %{overall['x2_60']} · rug %{overall['rugged']} · "
                 f"1s sonu {overall['median_ret60']}x")
    for code, s in rows:
        lines.append(f"<code>{escape(code, quote=False)}</code> ({s['n']}): 1s 2x %{s['x2_60']} · "
                     f"rug %{s['rugged']} · 1s sonu {s['median_ret60']}x")
    if not rows:
        lines.append("En az 5 sinyalde görülen bulgu yok.")
    hint = ("Bir çöp nedeni \"Hepsi\"nden iyi sonuç veriyorsa iyi coinleri eliyor olabilir." if pons else
            "Bir bulgu \"Hepsi\"nden iyi sonuç veriyorsa güven skorunu gereksiz düşürüyor olabilir.")
    lines += ["", f"<i>{hint}</i>"]
    return "\n".join(lines)


def format_analysis(hours: float, n: int, table: list[tuple[str, list[tuple[str, dict]]]]) -> list[str]:
    """/analiz: each feature split into thirds, with how each third did."""
    blocks = [f"🔬 <b>Özellik analizi — son {hours:g} saat</b>\n"
              f"<i>({n} sinyal: bildirim + filtre + gölge; her özellik değerine göre üçe bölündü)\n"
              f"Her dilim: 1 saatte 2x % · 24s içinde 5x % · rug % · (sinyal sayısı)</i>\n"]
    for label, parts in table:
        rows = [f"<b>{escape(label, quote=False)}</b>"]
        for tag, s in parts:
            rows.append(f"   {escape(tag, quote=False)}: 2x %{s['x2_60']} · 5x %{s['x5_all']} · rug %{s['rugged']} ({s['n']})")
        blocks.append("\n".join(rows))
    if not table:
        blocks.append("Yeterli veri yok (özellik başına en az 30 sinyal gerekiyor).")
    blocks.append("\n<i>Dilimler arasında büyük fark olan özellikler sinyali gerçekten ayırıyor; "
                  "fark yoksa o özelliğin puana etkisi azaltılabilir.</i>")
    return _chunks(blocks)


def _x(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value:.1f}x" if value < 10 else f"{value:.0f}x"


def _usd(value: float | None) -> str:
    if not value:
        return "?"
    return f"${value / 1e6:.1f}M" if value >= 1e6 else f"${value / 1e3:.0f}k"


def _entry(s: dict) -> str:
    if not s.get("entry_vs_start"):
        return "giriş fiyatı yok"
    text = f"giriş fiyatı başlangıcın {_x(s['entry_vs_start'])}'i"
    if s.get("peak_after") is not None:
        text += f", sonrası en fazla {_x(s['peak_after'])}"
    if s.get("before_peak") is False:
        text += " (zirveden sonra)"
    return text


def format_winners(days: float, min_multiple: float, winners: list[dict], checked: int,
                   min_score: int, min_momentum: int, min_buyers: int) -> list[str]:
    """/kazananlar: each coin that ran, and what the bot did with it."""
    def status(w: dict) -> str:
        kinds = {s["kind"] for s in w["signals"]}
        return "alert" if "alert" in kinds else "filtered" if "filtered" in kinds else "shadow" if kinds else "none"

    icons = {"alert": "✅ bildirim", "filtered": "🚫 filtre", "shadow": "👤 sadece gölge", "none": "❓ görülmedi"}
    counts = {k: sum(1 for w in winners if status(w) == k) for k in icons}
    blocks = [f"🏆 <b>Kazanan otopsisi — son {days:g} gün, {min_multiple:g}x ve üstü</b>\n"
              f"<i>(GeckoTerminal'de bu sürede açılan en işlek {checked} havuz; çarpan ilk işlem saatinin kapanışından en yüksek saatlik kapanışa)</i>\n"
              f"{len(winners)} kazanan: " + " · ".join(f"{icons[k]} {n}" for k, n in counts.items()) + "\n"]
    for i, w in enumerate(winners[:20], 1):
        lines = [f"{i}. <b>{escape(w['symbol'], quote=False)}</b> {_x(w['multiple'])} · "
                 f"{w['hours_to_peak']:.0f} saatte zirve · zirvede FDV {_usd(w.get('peak_fdv'))}"]
        by_kind = {}
        for s in w["signals"]:
            by_kind.setdefault(s["kind"], s)
        st = status(w)
        if st == "alert":
            s = by_kind["alert"]
            lines.append(f"   ✅ Bildirim gitti (güven {s['trust']}, momentum {s['momentum']}) — {_entry(s)}")
        elif st == "filtered":
            s = by_kind["filtered"]
            passes = (s["trust"] or 0) >= min_score and (s["momentum"] or 0) >= min_momentum
            codes = ", ".join((s["features"].get("findings") or [])[:4])
            lines.append(f"   🚫 Filtreye takıldı (güven {s['trust']}, momentum {s['momentum']}) — {_entry(s)}\n"
                         f"      bugünkü eşiklerle (skor ≥{min_score}, momentum ≥{min_momentum}) "
                         f"{'GÖNDERİLİRDİ' if passes else 'yine elenirdi'}" + (f" · bulgular: {escape(codes)}" if codes else ""))
        elif st == "shadow":
            s = by_kind["shadow"]
            buyers = s["features"].get("buyers_10m")
            lines.append(f"   👤 Sadece gölge grupta: Fomo'da 10 dk'da {buyers} alıcı "
                         f"(bildirim eşiği {min_buyers}) — {_entry(s)}")
        else:
            lines.append("   ❓ Hiç görülmedi: Fomo'da alım eşiğin yarısına bile ulaşmadı (ya da bot o sırada kapalıydı)")
        shadow = by_kind.get("shadow")
        if st in ("alert", "filtered") and shadow and shadow["ts"] < by_kind[st]["ts"]:
            lines.append(f"      (gölgede {(by_kind[st]['ts'] - shadow['ts']) / 60:.0f} dk önce görülmüştü, {_entry(shadow)})")
        blocks.append("\n".join(lines))
    if not winners:
        blocks.append(f"Bu sürede {min_multiple:g}x yapan coin bulunamadı.")
    return _chunks(blocks)


def format_backtest(hours: float, min_score: int, min_momentum: int, halves: list[tuple[str, dict]],
                    v2_on: bool) -> list[str]:
    """/geritest: which past signals v1 and v2 momentum would have alerted on, and how those did."""
    def line(title: str, s: dict) -> str:
        if not s.get("n"):
            return f"   {title}: yok"
        return (f"   {title} ({s['n']}): 2x %{s['x2_60']} · 5x %{s['x5_all']} · rug %{s['rugged']} · "
                f"1s sonu {s['median_ret60']}x")

    blocks = [f"🧪 <b>Geri test — son {hours:g} saat</b>\n"
              f"<i>Analiz edilen sinyaller; bildirim kuralı: güven ≥{min_score} ve momentum ≥{min_momentum}.\n"
              f"v2 ağırlıkları tüm dönemden çıkarıldı; asıl sınav \"Yeni yarı\".\n"
              f"Şu an kullanılan: {'v2' if v2_on else 'v1'}</i>\n"]
    for name, g in halves:
        blocks.append("\n".join([
            f"<b>{name}</b> (analiz edilen {g['all'].get('n', 0)})",
            line("v1 bildirirdi", g["v1"]),
            line("v2 bildirirdi", g["v2"]),
            line("sadece v2 ekler", g["added"]),
            line("v2 çıkarır", g["dropped"]),
        ]))
    blocks.append("\n<i>v2, \"Yeni yarı\"da da v1'den iyiyse (daha yüksek 2x/5x, rug benzer) /momentumv2 ac ile açılabilir.</i>")
    return _chunks(blocks)


def format_strategies(hours: float, position: float, rows: list[tuple[str, dict]]) -> list[str]:
    """/strateji: exit rules replayed on past alerts, with Fomo's fees."""
    first = next((r for _, r in rows if r.get("n")), {})
    n, exits = first.get("n", 0), first.get("exits", 0)
    blocks = [f"🎯 <b>Çıkış stratejileri — son {hours:g} saatin bildirimleri</b>\n"
              f"<i>({n} bildirim, {exits} tanesinde 🔴 ÇIK var; her birine ${position:g} girilmiş gibi, "
              f"Fomo komisyonu dahil. "
              f"Fiyatlar 5-60 dk aralıklı ölçümlerden; aradaki iğneler görülmez.)</i>\n"]
    ranked = sorted((r for r in rows if r[1].get("n")), key=lambda r: -r[1]["total"])
    for i, (name, r) in enumerate(ranked, 1):
        sign = "+" if r["total"] >= 0 else ""
        blocks.append(f"{i}. <b>{escape(name, quote=False)}</b>\n"
                      f"   toplam {sign}${r['total']:,.2f} · işlem başı {r['per_trade']:+.2f}$ · "
                      f"kazanan işlem %{r['win_rate']}\n"
                      f"   en iyi işlem +${r['best']:,.2f} · o olmasa toplam {r['without_best']:+,.2f}$")
    if not ranked:
        blocks.append("Yeterli veri yok (en az 1 günlük bildirim gerekiyor).")
    blocks.append("\n<i>Geçmiş sonuç gelecek garantisi değildir; asıl karar yine kim satıyor sorusuna göre.</i>")
    return _chunks(blocks)
