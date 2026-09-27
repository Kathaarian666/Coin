"""Formats a report as a Telegram HTML message (Turkish)."""

import time
from html import escape

from .config import DEXSCREENER_CHAIN
from .momentum import momentum_label
from .outcomes import blocking_gates, momentum_v2_of, rug_risk_of
from .rugrisk import HIGH_RISK
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
    risk = report.get("rug_risk") or {}
    if (risk.get("score") or 0) >= HIGH_RISK:
        lines.append(f"⚠️ <b>Rug riski yüksek</b> ({risk['score']}/100) — "
                     + escape(", ".join(risk["reasons"][:3]), quote=False))
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
            f"   1 saatte 2x: %{s['x2_60']} · 1.5x: %{s['up50_60']} · 24s içinde 2x: %{s['x2_all']} · 5x: %{s['x5_all']} "
            f"(kalıcı %{s['x5_held']})\n"
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
              f"Her dilim: 1 saatte 2x % · 24s içinde 5x % (kalıcı 5x %) · rug % · (sinyal sayısı)</i>\n"]
    for label, parts in table:
        rows = [f"<b>{escape(label, quote=False)}</b>"]
        for tag, s in parts:
            rows.append(f"   {escape(tag, quote=False)}: 2x %{s['x2_60']} · 5x %{s['x5_all']} (kalıcı %{s['x5_held']}) · "
                        f"rug %{s['rugged']} ({s['n']})")
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
                   bars: dict, candidates: int | None = None) -> list[str]:
    """/kazananlar: each coin that ran, what the bot saw of it, and which of today's bars would stop it.

    bars: min_score, min_momentum, min_buyers, min_buy_usd (today's settings)."""
    def status(w: dict) -> str:
        kinds = {s["kind"] for s in w["signals"]}
        return "alert" if "alert" in kinds else "filtered" if "filtered" in kinds else "shadow" if kinds else "none"

    def first_passing(w: dict) -> dict | None:
        """The earliest analysed signal (alert or filtered) that today's bars would alert on."""
        return next((s for s in w["signals"] if s["kind"] in ("alert", "filtered")
                     and not blocking_gates(s, **bars)), None)

    icons = {"alert": "✅ bildirim", "filtered": "🚫 filtre", "shadow": "👤 sadece gölge", "none": "❓ görülmedi"}
    counts = {k: sum(1 for w in winners if status(w) == k) for k in icons}
    caught = [s for w in winners if (s := first_passing(w))]
    early = sum(1 for s in caught if (s.get("entry_vs_start") or 99) <= 2)
    blocks = [f"🏆 <b>Kazanan otopsisi — son {days:g} gün, {min_multiple:g}x ve üstü</b>\n"
              f"<i>(GeckoTerminal'de bu sürede açılan en işlek {checked} havuz"
              + (f" — süre sınırı yüzünden {candidates} adaydan {checked}'i tarandı" if candidates and checked < candidates else "")
              + "; çarpan ilk işlem saatinin kapanışından en yüksek saatlik kapanışa)</i>\n"
              f"{len(winners)} kazanan: " + " · ".join(f"{icons[k]} {n}" for k, n in counts.items()) + "\n"
              f"<b>Bugünkü eşiklerle yakalanırdı: {len(caught)}/{len(winners)}</b> · erken (başlangıcın ≤2x'inde): {early}\n"
              f"<i>Eşikler: alıcı ≥{bars['min_buyers']}, 10 dk alım ≥${bars['min_buy_usd']:,.0f}, "
              f"güven ≥{bars['min_score']}, momentum (v2) ≥{bars['min_momentum']}"
              + (f", rug riski &lt;{bars['max_rug']}" if bars.get("max_rug", 101) <= 100 else "") + "</i>\n"]
    for i, w in enumerate(winners[:20], 1):
        lines = [f"{i}. <b>{escape(w['symbol'], quote=False)}</b> {_x(w['multiple'])} · "
                 f"{w['hours_to_peak']:.0f} saatte zirve · zirvede FDV {_usd(w.get('peak_fdv'))}"]
        by_kind: dict[str, dict] = {}
        for s in w["signals"]:
            by_kind.setdefault(s["kind"], s)
        st = status(w)
        if st == "none":
            lines.append("   ❓ Hiç görülmedi: Fomo'da alım eşiğin yarısına bile ulaşmadı (ya da bot o sırada kapalıydı)")
        else:
            s = by_kind[st]
            head = {"alert": "✅ Bildirim gitti", "filtered": "🚫 Filtreye takıldı",
                    "shadow": "👤 Sadece gölge grupta (analiz edilmedi)"}[st]
            values = [f"alıcı {s['features'].get('buyers_10m')}"]
            if s.get("trust") is not None:
                values.append(f"güven {s['trust']}")
            if momentum_v2_of(s) is not None:
                values.append(f"momentum {momentum_v2_of(s)}")
            lines.append(f"   {head} ({', '.join(values)}) — {_entry(s)}")
            gates = blocking_gates(s, **bars)
            if gates:
                lines.append(f"      ⛔ bugün engelleyen: {escape(', '.join(gates), quote=False)}")
            elif st != "alert":
                lines.append("      ✅ bugünkü eşiklerin hepsini geçiyor" + (" (ama güven ölçülmedi)" if st == "shadow" else ""))
            codes = ", ".join((s["features"].get("findings") or [])[:4])
            if st == "filtered" and codes:
                lines.append(f"      bulgular: {escape(codes, quote=False)}")
            shadow = by_kind.get("shadow")
            if st != "shadow" and shadow and shadow["ts"] < s["ts"]:
                lines.append(f"      (gölgede {(s['ts'] - shadow['ts']) / 60:.0f} dk önce görülmüştü, {_entry(shadow)})")
        blocks.append("\n".join(lines))
    if not winners:
        blocks.append(f"Bu sürede {min_multiple:g}x yapan coin bulunamadı.")
    return _chunks(blocks)


def format_backtest(hours: float, min_score: int, min_momentum: int, halves: list[tuple[str, dict]],
                    v2_on: bool, lower: dict | None = None, min_buyers: int = 10) -> list[str]:
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
    if lower is not None:
        blocks.append("\n".join([
            f"<b>Küçük coinlerde alıcı eşiği 8 olsaydı</b> (gölgede kalan 8-{min_buyers - 1} alıcılı, "
            f"FDV &lt;$20k, v2 momentum ≥{min_momentum})",
            line("fazladan bildirilirdi", lower),
            "   <i>(gölgeler için FDV bu güncellemeden beri kaydediliyor; veri birikince dolar)</i>",
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


def format_sweep(hours: float, total: int, winners: int, rows: list[dict], current: tuple[int, int],
                 rug_rows: list[tuple[str, dict]] | None = None) -> list[str]:
    """/tarama: alert bars side by side; sorted by the share of 5x signals caught, then by precision."""
    blocks = [f"🎛 <b>Parametre taraması — son {hours:g} saat</b>\n"
              f"<i>{total} analiz edilen sinyal, {winners} tanesi 24 saat içinde 5x yaptı.\n"
              f"Her satır: min momentum (v2) / min güven → bildirim sayısı · 1s 2x % · 5x % · rug % · "
              f"5x'lerin yakalanan payı</i>\n"]
    ranked = sorted(rows, key=lambda r: (-(r["x5_all"] * (r["recall"] or 0)), -r["x5_all"]))
    for r in ranked[:20]:
        mark = " ◀ şu an" if (r["min_momentum"], r["min_score"]) == current else ""
        blocks.append(f"<b>{r['min_momentum']} / {r['min_score']}</b>: {r['n']} bildirim · 2x %{r['x2_60']} · "
                      f"5x %{r['x5_all']} (kalıcı %{r['x5_held']}) · rug %{r['rugged']} · yakalanan %{r['recall']}{mark}")
    if not rows:
        blocks.append("Yeterli veri yok.")
    if rug_rows:
        blocks.append(f"\n<b>Rug riski filtresi</b> (şu anki eşiklerle: momentum ≥{current[0]}, güven ≥{current[1]})")
        for name, r in rug_rows:
            name = escape(name, quote=False)
            if not r.get("n"):
                blocks.append(f"   {name}: bildirim kalmaz")
                continue
            blocks.append(f"   {name}: {r['n']} bildirim · 2x %{r['x2_60']} · 5x %{r['x5_all']} "
                          f"(kalıcı %{r['x5_held']}) · rug %{r['rugged']} · kalıcı 5x'lerden kalan "
                          f"{r['kept_winners']}/{r['winners']}")
    blocks.append("\n<i>Sıralama: isabet (5x %) × yakalama (5x'lerin payı). Az bildirim + yüksek isabet ile "
                  "çok bildirim + yüksek yakalama arasında denge ara. Aynı veriden seçildiği için biraz iyimserdir.</i>")
    return _chunks(blocks)


SIGNAL_FIELDS = [
    ("buyers_10m", "10 dk alıcı", "{:.0f}"), ("buyers_5m", "son 5 dk alıcı", "{:.0f}"),
    ("buyers_prev_5m", "önceki 5 dk alıcı", "{:.0f}"), ("buy_usd_10m", "10 dk alım", "${:,.0f}"),
    ("hold_rate_30m", "tutma oranı", "{:.2f}"), ("whale_share_10m", "en büyük alıcı payı", "{:.2f}"),
    ("buy_ratio_10m", "alım oranı", "{:.2f}"), ("smart_buyers_10m", "akıllı cüzdan", "{:.0f}"),
    ("fomo_share_h1", "Fomo hacim payı", "{:.2f}"), ("age_min", "yaş (dk)", "{:.0f}"),
    ("fdv", "FDV", "${:,.0f}"), ("liquidity_usd", "likidite", "${:,.0f}"),
    ("top10_pct", "ilk 10 cüzdan %", "{:.1f}"), ("sniper_pct", "sniper %", "{:.1f}"),
    ("dev_pct", "dev %", "{:.1f}"), ("market_buyers_1h", "piyasa (1s tüm alıcı)", "{:.0f}"),
    ("momentum_v1", "momentum v1", "{:.0f}"), ("momentum_v2", "momentum v2", "{:.0f}"),
]
KIND_TITLES = {"alert": "🔔 Bildirim", "filtered": "🚫 Filtre", "shadow": "👤 Gölge", "wave2": "🔁 İkinci dalga",
               "exit": "🔴 ÇIK", "caution": "🟠 DİKKAT"}


def format_signal(symbol: str, signals: list[dict], outcomes: dict[str, dict]) -> str:
    """/sinyal: everything recorded about one coin's signals, to see what set a winner apart."""
    lines = [f"🔍 <b>{escape(symbol, quote=False)}</b> — kayıtlı sinyaller", ""]
    if not signals:
        return "\n".join(lines + ["Bu coin için kayıtlı sinyal yok."])
    for s in signals:
        f = s.get("features") or {}
        ago = (time.time() - s["ts"]) / 3600
        head = f"<b>{KIND_TITLES.get(s['kind'], s['kind'])}</b> · {ago:.1f} saat önce"
        if s.get("trust") is not None:
            head += f" · güven {s['trust']}"
        if s.get("momentum") is not None:
            head += f" · momentum {s['momentum']}"
        lines.append(head)
        values = [f"{label} {fmt.format(f[key])}" for key, label, fmt in SIGNAL_FIELDS
                  if isinstance(f.get(key), (int, float)) and not isinstance(f.get(key), bool)]
        if f.get("buyers_10m") and f.get("buy_usd_10m") is not None:
            values.append(f"alıcı başına ${f['buy_usd_10m'] / f['buyers_10m']:,.0f}")
        values.append(f"rug riski {rug_risk_of(s)}")
        lines.append("   " + escape(" · ".join(values), quote=False))
        if f.get("findings"):
            lines.append("   bulgular: " + escape(", ".join(f["findings"]), quote=False))
        o = outcomes.get(s["kind"])
        if o:
            lines.append(f"   sonuç: 1s zirve {_x(o['max_60'])} · 24s zirve {_x(o['max_all'])} "
                         f"(kalıcı {_x(o.get('held_all'))}) · 1s sonu {_x(o['ret_60'])}" + (" · RUG" if o["rugged"] else ""))
        elif not s.get("p0"):
            lines.append("   sonuç: başlangıç fiyatı yok, ölçülemedi")
        lines.append("")
    return "\n".join(lines)
