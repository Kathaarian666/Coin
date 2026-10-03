"""The safety report of an alert (PROJE.md §1 "Güvenlik — rapor", §0 D1/D2).

Besides the elimination (unsellable: live.sell_gate), the 14 other checks of step 1 are shown one by one, in a fixed
order, each ✅ (fine) / ⚠️ (a warning) / ❔ (unknown — nothing could be read); none of them eliminates. The only score
is the trust model's (live.trust_score: weights from the past trap rates, §4.1). Sources: our chain checks
(analyzer.Analyzer.analyze), the bot's Fomo tracker, and as a second opinion GoPlus, GeckoTerminal and DexScreener
(free; they often know nothing yet about a minutes-old coin, which then reads "bilinmiyor").
"""

import asyncio
import logging

import httpx

from .hooks import NAMED_HOOKS
from .live import LAUNCHPAD_OWNERS

log = logging.getLogger(__name__)

GOPLUS_URL = "https://api.gopluslabs.io/api/v1/token_security/4663"
GECKO_URL = "https://api.geckoterminal.com/api/v2/networks/robinhood/tokens/{}/info"
ZERO = "0x" + "0" * 40
OK, WARN, UNKNOWN = "ok", "warn", "unknown"
CHECKS = ("Fomo'da satış", "Kontrat fonksiyonları", "Yükseltilebilir kontrat", "Sahiplik", "Kaynak kodu doğrulanmış",
          "Likidite", "LP kilidi", "V4 hook", "Holder dağılımı", "Geliştirici payı / satışı", "Bundle / sniper",
          "Geliştirici geçmişi", "Sahte hacim", "Piyasa bilgisi")
RISKY_NAMES = {"mint": "mint", "blacklist": "kara liste", "fees": "vergi değiştirme", "pause": "durdurma",
               "limits": "işlem limiti", "trading": "trading aç/kapa", "upgrade": "yükseltme"}


async def goplus(http: httpx.AsyncClient, token: str) -> dict | None:
    try:
        r = await http.get(GOPLUS_URL, params={"contract_addresses": token}, timeout=10)
        return ((r.json().get("result") or {}).get(token.lower())) or None
    except Exception as exc:
        log.debug("GoPlus %s: %s", token, exc)
        return None


async def gecko(http: httpx.AsyncClient, token: str) -> dict | None:
    try:
        r = await http.get(GECKO_URL.format(token), timeout=10)
        return ((r.json().get("data") or {}).get("attributes")) or None
    except Exception as exc:
        log.debug("GeckoTerminal %s: %s", token, exc)
        return None


async def second_opinions(http: httpx.AsyncClient, token: str) -> tuple[dict | None, dict | None]:
    return tuple(await asyncio.gather(goplus(http, token), gecko(http, token)))


def _usd(x: float) -> str:
    return f"${x / 1e6:.2f}M" if x >= 1e6 else f"${x / 1e3:.1f}K" if x >= 1e3 else f"${x:,.0f}"


def _flag(d: dict | None, key: str) -> bool | None:
    v = (d or {}).get(key)
    return None if v in (None, "") else str(v) == "1"


def checklist(report: dict, sellers: int, pons: bool, depth_usd: float | None, gp: dict | None,
              gt: dict | None) -> list[tuple[str, str, str]]:
    """The 14 checks: (name, ok / warn / unknown, what was seen)."""
    codes = {f["code"]: f["message"] for f in report.get("findings", [])}
    contract = report.get("contract")
    liq = report.get("liquidity") or {}
    holders = report.get("holders") or {}
    launch = report.get("launch") or {}
    deployer = report.get("deployer") or {}
    market = report.get("market") or {}
    out = []

    # 1. sold on Fomo
    if sellers >= 2:
        out.append((OK, f"{sellers} farklı Fomo kullanıcısı satabildi"))
    elif sellers == 1:
        out.append((WARN, "sadece 1 Fomo kullanıcısı sattı"))
    else:
        out.append((UNKNOWN, "son 1 saatte Fomo'da satış görülmedi"))

    # 2. risky contract functions (+ GoPlus)
    gp_bad = [n for k, n in (("is_mintable", "mint"), ("is_blacklisted", "kara liste"), ("transfer_pausable", "durdurma"),
                             ("slippage_modifiable", "vergi değiştirme")) if _flag(gp, k)]
    if contract is None:
        out.append((UNKNOWN, "kontrat okunamadı"))
    else:
        risky = [RISKY_NAMES.get(g, g) for g in (contract.get("risky_functions") or {})]
        template = " (şablon kopyası)" if contract.get("clone_of") else ""
        if risky and not contract.get("renounced"):
            out.append((WARN, f"{', '.join(risky)} var, sahibi kullanabilir{template}"))
        elif risky:
            out.append((OK, f"{', '.join(risky)} var ama sahip yok, etkisiz{template}"))
        else:
            out.append((OK, f"riskli fonksiyon yok{template}"))
    if gp_bad:
        status, text = out[-1]
        out[-1] = (WARN, f"{text} · GoPlus: {', '.join(gp_bad)}")

    # 3. upgradeable
    if contract is None:
        out.append((UNKNOWN, "kontrat okunamadı"))
    elif contract.get("proxy_implementation") or _flag(gp, "is_proxy"):
        out.append((WARN, "yükseltilebilir proxy: geliştirici kodu değiştirebilir"))
    else:
        out.append((OK, "değiştirilemez"))

    # 4. owner
    if contract is None or "renounced" not in contract:
        out.append((UNKNOWN, "sahip okunamadı"))
    elif contract.get("renounced"):
        out.append((OK, "sahibi yok (devredilmiş)"))
    elif (contract.get("owner") or "").lower() in LAUNCHPAD_OWNERS:
        out.append((OK, "sahibi ortak launchpad kontratı (~1.500 Fomo coininin sahibi; geçmişte bu grupta tuzak yok)"))
    elif contract.get("owner_is_contract"):
        out.append((WARN, "sahibi bir kontrat (launchpad ya da multisig olabilir)"))
    else:
        out.append((WARN, "kontratın hâlâ bir sahibi var"))
    if _flag(gp, "hidden_owner") or _flag(gp, "can_take_back_ownership"):
        out[-1] = (WARN, out[-1][1] + " · GoPlus: gizli sahip / sahipliği geri alabilir")

    # 5. verified source
    verified = (contract or {}).get("verified")
    if verified is None:
        verified = _flag(gp, "is_open_source")
    out.append((UNKNOWN, "bilinmiyor") if verified is None else
               (OK, "kaynak kodu doğrulanmış") if verified else (WARN, "kaynak kodu doğrulanmamış"))

    # 6. liquidity
    if market.get("liquidity_usd"):
        usd = float(market["liquidity_usd"])
        out.append((OK if usd >= 1000 else WARN, f"{_usd(usd)} (DexScreener)"))
    elif "liquidity_eth" in liq:
        out.append((OK if liq["liquidity_eth"] >= 0.5 else WARN, f"{liq['liquidity_eth']:.2f} ETH"))
    elif depth_usd and depth_usd == depth_usd:
        usd = 2 * depth_usd
        out.append((OK if usd >= 1000 else WARN, f"~{_usd(usd)} (Fomo alımlarının fiyat etkisinden tahmin)"))
    else:
        out.append((UNKNOWN, "bilinmiyor"))

    # 7. LP lock
    if liq.get("lp_burned_pct") is not None:
        pct = liq["lp_burned_pct"]
        out.append((OK if pct >= 95 else WARN, f"LP'nin %{pct:.0f}'i yakılmış"))
    elif pons and not report.get("pool"):
        out.append((OK, "Pons curve'ünde: mezuniyete kadar likidite çekilemez"))
    elif "v4_known_hook" in codes:
        out.append((OK, "likidite launchpad hook'unda"))
    else:
        out.append((UNKNOWN, "bilinmiyor"))

    # 8. V4 hook
    hooks = (liq.get("hooks") or "").lower() or None
    named = {h.lower() for h in NAMED_HOOKS}
    if not hooks:
        out.append((OK, "Pons curve'ünde, havuz yok") if pons and not report.get("pool") else (UNKNOWN, "bilinmiyor"))
    elif hooks == ZERO:
        out.append((WARN, "hook'suz düz havuz (geçmişte bu grupta tuzak oranı yüksek)"))
    elif hooks in named:
        out.append((OK, f"bilinen launchpad hook'u ({NAMED_HOOKS.get(hooks, 'Pons')})"))
    else:
        out.append((WARN, "bilinmeyen hook: alım-satımı etkileyebilir"))

    # 9. holders (+ GeckoTerminal)
    top10 = holders.get("top10_pct")
    gt_top10 = ((gt or {}).get("holders") or {}).get("distribution_percentage", {}).get("top_10")
    if top10 is not None:
        largest = holders.get("largest_pct") or 0
        bad = top10 > 50 or largest > 15
        out.append((WARN if bad else OK, f"ilk 10 cüzdan %{top10:.0f}, en büyük %{largest:.0f}"))
    elif gt_top10 is not None:
        out.append((WARN if float(gt_top10) > 50 else OK, f"ilk 10 cüzdan %{float(gt_top10):.0f} (GeckoTerminal)"))
    else:
        out.append((UNKNOWN, "bilinmiyor"))

    # 10. developer share / selling
    if launch.get("dev_pct") is not None:
        now, first = launch["dev_pct"], launch.get("dev_initial_pct") or 0
        sold = first > 0 and now < first / 2
        text = f"geliştirici %{now:.1f} tutuyor (lansmanda %{first:.1f})" + (", yarısından fazlasını sattı" if sold else "")
        out.append((WARN if now > 5 else OK, text))
    elif (gp or {}).get("creator_percent") not in (None, ""):
        pct = 100 * float(gp["creator_percent"])
        out.append((WARN if pct > 5 else OK, f"geliştirici %{pct:.1f} (GoPlus)"))
    else:
        out.append((UNKNOWN, "bilinmiyor"))

    # 11. bundle / sniper
    if launch.get("sniper_pct") is not None or launch.get("bundle_pct") is not None:
        sn, bu = launch.get("sniper_pct") or 0, launch.get("bundle_pct") or 0
        out.append((WARN if sn > 25 or bu > 10 else OK, f"sniper %{sn:.0f}, bundle %{bu:.0f}"))
    else:
        out.append((UNKNOWN, "bilinmiyor"))

    # 12. developer history
    prev = deployer.get("previous_launches")
    if prev is None:
        out.append((UNKNOWN, "bilinmiyor"))
    elif prev == 0:
        out.append((OK, "geliştiricinin ilk coini"))
    else:
        more = "+" if deployer.get("partial") else ""
        alive = (f", son {deployer['checked']} coinden {deployer.get('alive', 0)} tanesi yaşıyor"
                 if deployer.get("checked") else "")
        bad = "launcher_dead_coins" in codes or "serial_launcher" in codes
        out.append((WARN if bad else OK, f"{prev}{more} önceki coin{alive}"))

    # 13. fake volume
    wash = [codes[c] for c in ("wash_fomo_churn", "wash_one_wallet", "wash_few_wallets") if c in codes]
    if wash:
        out.append((WARN, "; ".join(wash)))
    elif (report.get("wash") or {}).get("transfers_5m") is not None:
        out.append((OK, "belirti yok"))
    else:
        out.append((UNKNOWN, "bilinmiyor"))

    # 14. market info (DexScreener, GeckoTerminal)
    parts = []
    if gt and gt.get("gt_score") is not None:
        parts.append(f"GeckoTerminal puanı {float(gt['gt_score']):.0f}/100")
    if market.get("socials"):
        parts.append("sosyal hesap var")
    if market.get("buys_h1") is not None:
        parts.append(f"son 1 saat {market['buys_h1']} alım / {market['sells_h1']} satış")
    if parts:
        low = gt and gt.get("gt_score") is not None and float(gt["gt_score"]) < 40
        out.append((WARN if low else OK, " · ".join(parts)))
    else:
        out.append((UNKNOWN, "henüz piyasa sitelerinde yok"))

    return [(name, status, text) for name, (status, text) in zip(CHECKS, out)]


def sources(report: dict, gp: dict | None, gt: dict | None) -> list[tuple[str, bool]]:
    return [("zincir", True), ("GoPlus", gp is not None), ("GeckoTerminal", gt is not None),
            ("DexScreener", bool((report.get("market") or {}).get("pair")))]
