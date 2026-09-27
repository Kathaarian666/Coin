"""Telegram bot: pushes alerts for tokens rising on Fomo and answers /check requests."""

import asyncio
import logging
import time
from dataclasses import dataclass
from html import escape

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from .analyzer import Analyzer, market_summary
from .checks.wash import fomo_churn
from .config import Settings
from .discovery import NewPool, PoolWatcher
from .fomo import FomoTrade, FomoTracker, FomoWatcher
from .hooks import REGISTRY
from .exits import STRONG, WARNING, Snapshot, breakeven_multiple, evaluate_exit, exit_level
from .momentum import fomo_features, momentum_score
from .outcomes import OutcomeLog, finding_table, momentum_bucket, summarize, summarize_exits, trust_bucket
from .pons import BLOCKS_PER_MIN, DAY_BLOCKS_PONS, PonsTracker, PonsWatcher, junk_reasons
from .report import format_exit, format_findings, format_followup, format_report, format_scorecard
from .rpc import RpcClient
from .sources import Blockscout, DexScreener
from .storage import Storage
from .wallets import WalletBook

log = logging.getLogger(__name__)

HELP = (
    "🤖 <b>Robinhood Chain · Fomo Token Tarayıcı</b>\n\n"
    "Fomo kullanıcılarının Robinhood Chain'de aldığı coinleri canlı izler. Bir coini kısa sürede "
    "yeterince farklı kişi alınca güvenlik taraması yapıp sonucu gönderir.\n\n"
    "/trend — şu an Fomo'da en çok alınan coinler\n"
    "/check &lt;adres&gt; — bir token'ı hemen analiz et\n"
    "/minskor &lt;0-100&gt; — bu skorun altındakiler için bildirim gönderme\n"
    "/minmomentum &lt;0-100&gt; — momentumu bunun altındakiler için bildirim gönderme (0 = kapalı)\n"
    "/minalici &lt;sayı&gt; — bildirim için gereken farklı Fomo alıcısı sayısı\n"
    "/minhacim &lt;$&gt; — bildirim için gereken en az Fomo alım hacmi\n"
    "/durdur — otomatik bildirimleri durdur\n"
    "/devam — otomatik bildirimleri aç\n"
    "/durum — tarayıcı durumu\n"
    "/karne [saat] — sinyallerin sonuçları (varsayılan son 24 saat)\n"
    "/bulgular [saat] [pons|erken] — güven bulgularına (veya Pons çöp nedenlerine) göre sonuçlar\n"
    "/pozisyon &lt;$&gt; — işlem tutarınız (komisyonla başa baş hesabı için)\n"
    "/akilli — kazanma oranı yüksek Fomo cüzdanları\n"
)


@dataclass
class Job:
    token: str
    pool: dict | None = None
    from_fomo: bool = False
    delay: float = 0.0


class ScannerApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.http = httpx.AsyncClient(timeout=20)
        self.rpc = RpcClient(settings.rpc_url, settings.rpc_max_rps, fallback_urls=settings.rpc_fallback_urls)
        self.analyzer = Analyzer(
            self.rpc,
            settings,
            Blockscout(settings.blockscout_url, self.http),
            DexScreener(self.http) if settings.use_dexscreener else None,
            self.storage,
        )
        self.tracker = FomoTracker()
        self.outcomes = OutcomeLog(self.storage.db)
        self.wallets = WalletBook(self.storage.db)
        self.pons = PonsTracker(max_age=settings.pons_max_age_min * 60)
        self.pons_seen: set[tuple[str, str]] = {(row[0], row[1].removesuffix("_junk")) for row in self.storage.db.execute(
            "SELECT token, kind FROM signals WHERE kind LIKE 'pons%' AND ts >= ?", (time.time() - 86400,))}
        self.eth_usd: float | None = None
        self.eth_usd_at = 0.0
        self.symbols: dict[str, str] = {}
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []
        self.followups: set[asyncio.Task] = set()
        self.app: Application | None = None

    # --- settings kept in the database so they survive restarts ---
    @property
    def min_score(self) -> int:
        return int(self.storage.get_state("min_score", str(self.settings.min_score_alert)))

    @property
    def min_momentum(self) -> int:
        return int(self.storage.get_state("min_momentum", "0"))

    @property
    def min_buyers(self) -> int:
        return int(self.storage.get_state("min_buyers", str(self.settings.fomo_min_buyers)))

    @property
    def min_buy_usd(self) -> float:
        return float(self.storage.get_state("min_buy_usd", str(self.settings.fomo_min_buy_usd)))

    @property
    def position_usd(self) -> float:
        return float(self.storage.get_state("position_usd", str(self.settings.position_usd)))

    @property
    def alerts_on(self) -> bool:
        return self.storage.get_state("alerts_on", "1") == "1"

    @property
    def fomo_window(self) -> float:
        return self.settings.fomo_window_min * 60

    def _authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        return bool(chat) and chat.id in self.settings.telegram_chat_ids

    # --- sources ---
    async def on_fomo_trades(self, trades: list[FomoTrade], warmup: bool = False):
        self.wallets.add(trades)
        for token in {t.token for t in trades if t.side == "buy"}:
            stats = self.tracker.stats(token, self.fomo_window)
            if not warmup and self._is_shadow(stats):
                self.outcomes.record(token, "shadow", features=fomo_features(self.tracker, token))
            rising = stats["buyers"] >= self.min_buyers and stats["buy_usd"] >= self.min_buy_usd
            if rising and self.storage.mark_alerted(token):
                if warmup:
                    # Already trending when the bot started: visible in /trend, no alert flood.
                    log.info("%s was already trending at startup; not alerting", token)
                    continue
                log.info("%s is rising on Fomo: %s", token, stats)
                await self.queue.put(Job(token, from_fomo=True))

    async def on_pool(self, pool: NewPool):
        pool_dict = _pool_dict(pool)
        if self.storage.mark_seen(pool.token, pool_dict, pool.block) and self.storage.mark_alerted(pool.token):
            log.info("new %s pool for %s (%s)", pool.dex, pool.token, pool.pool)
            # Give indexers a moment to see the token and its first holders.
            await self.queue.put(Job(pool.token, pool_dict, delay=self.settings.analysis_delay))

    def pons_tiers(self) -> list[tuple[str, int, float]]:
        """Signal bars measured side by side: (kind, min distinct buyers, min USD bought) in 10 minutes."""
        return [("pons", self.settings.pons_min_buyers, self.settings.pons_min_buy_usd),
                ("pons_early", self.settings.pons_early_min_buyers, self.settings.pons_early_min_buy_usd)]

    async def on_pons_trades(self, trades, warmup: bool = False):
        """A young Pons coin that enough wallets are buying on its curve: recorded for /karne (no alert)."""
        if warmup or not self.eth_usd:
            return
        index = self.analyzer.launches
        for curve in {t.curve for t in trades if t.side == "buy"}:
            launch = index.by_curve(curve)
            if not launch:
                continue  # not indexed yet (the index syncs every 30 s; later buys retry)
            token, launcher, launch_block = launch
            tiers = [tier for tier in self.pons_tiers() if (token, tier[0]) not in self.pons_seen]
            if not tiers:
                continue
            head = max(t.block for t in trades)
            age_min = (head - launch_block) / BLOCKS_PER_MIN
            if age_min > self.settings.pons_max_age_min:
                continue
            stats = self.pons.stats(curve, launcher, launch_block, self.fomo_window)
            buy_usd = stats["buy_eth_10m"] * self.eth_usd
            launches_24h = None
            for kind, min_buyers, min_usd in tiers:
                if stats["buyers_10m"] < min_buyers or buy_usd < min_usd:
                    continue
                if launches_24h is None:
                    launches_24h = index.launches_since(launcher, head - DAY_BLOCKS_PONS)
                reasons = junk_reasons(stats, launches_24h)
                self.pons_seen.add((token, kind))
                features = {**stats, "buy_usd_10m": round(buy_usd, 2), "age_min": round(age_min, 1),
                            "launches_24h": launches_24h, "findings": reasons}
                self.outcomes.record(token, f"{kind}_junk" if reasons else kind, features=features, pair=None)
                log.info("Pons signal %s %s (%s): %s", kind, token, ",".join(reasons) or "clean", features)

    def pons_price(self, token: str) -> float | None:
        """USD price of a coin still on its Pons curve (last trade), for outcome sampling."""
        curve = self.analyzer.launches.curve_of(token) if self.analyzer.launches else None
        price = self.pons.price(curve) if curve else None
        return price * self.eth_usd if price and self.eth_usd else None

    async def refresh_eth_usd(self):
        if time.time() - self.eth_usd_at < 600 or not self.analyzer.dexscreener:
            return
        weth = self.settings.weth.lower()
        pairs = [p for p in await self.analyzer.dexscreener.tokens([weth])
                 if (p.get("baseToken") or {}).get("address", "").lower() == weth and p.get("priceUsd")]
        if pairs:
            best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
            self.eth_usd, self.eth_usd_at = float(best["priceUsd"]), time.time()

    def _is_shadow(self, stats: dict) -> bool:
        """A lower bar than alerts: the baseline group for measuring the filters."""
        return stats["buyers"] >= max(3, self.min_buyers // 2) and stats["buy_usd"] >= self.min_buy_usd / 5

    def attach_momentum(self, report: dict):
        features = fomo_features(self.tracker, report["token"])
        features["smart_buyers_10m"] = len(self.wallets.smart_buyers(self.tracker, report["token"]))
        features["churn_share_30m"] = fomo_churn(self.tracker, report["token"])
        features.update(report.get("wash") or {})
        report["fees"] = {
            "position": self.position_usd,
            "breakeven": breakeven_multiple(self.position_usd, self.settings.fomo_fee_pct, self.settings.fomo_fee_min_usd),
        }
        score, reasons, extra = momentum_score(features, report.get("market") or {}, report.get("launch"))
        report["momentum"] = {"score": score, "reasons": reasons, "features": {**features, **extra}}

    def shadow_momentum(self, features: dict, pairs: list[dict], pair_address: str | None) -> int:
        score, _, _ = momentum_score(features, market_summary(pairs, pair_address))
        return score

    def record_outcome(self, report: dict, kind: str):
        launch = report.get("launch") or {}
        features = {
            **(report.get("momentum") or {}).get("features", {}),
            "missing": report.get("missing"),
            "top10_pct": (report.get("holders") or {}).get("top10_pct"),
            **{k: launch.get(k) for k in ("dev_pct", "dev_initial_pct", "sniper_pct", "bundle_pct", "age_min")},
            "liquidity_usd": (report.get("market") or {}).get("liquidity_usd"),
            "fdv": (report.get("market") or {}).get("fdv"),
            "socials": (report.get("market") or {}).get("socials"),
            "findings": [f["code"] for f in report.get("findings", [])],
            **{k: (report.get("deployer") or {}).get(k)
               for k in ("previous_launches", "launches_24h", "checked", "alive", "best_previous_fdv")},
        }
        self.outcomes.record(
            report["token"], kind, trust=report["score"], momentum=(report.get("momentum") or {}).get("score"),
            features=features, pair=(report.get("pool") or {}).get("pool"),
        )

    async def outcome_loop(self):
        while True:
            try:
                if self.analyzer.dexscreener:
                    await self.refresh_eth_usd()
                    written = await self.outcomes.tick(self.analyzer.dexscreener, self.shadow_momentum,
                                                       price_fn=self.pons_price)
                    if written:
                        log.debug("outcome samples written: %d", written)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("outcome sampling failed")
            await asyncio.sleep(60)

    # --- analysis ---
    def fomo_stats(self, token: str) -> dict | None:
        stats = self.tracker.stats(token, self.fomo_window)
        return stats if stats["buys"] or stats["sells"] else None

    async def worker(self):
        while True:
            job = await self.queue.get()
            try:
                if job.delay:
                    await asyncio.sleep(job.delay)
                report = await self.analyzer.analyze(job.token, job.pool, self.fomo_stats(job.token))
                self.attach_momentum(report)
                self.storage.save_report(job.token, report["score"], report)
                momentum = (report.get("momentum") or {}).get("score") or 0
                sent = self.alerts_on and report["score"] >= self.min_score and momentum >= self.min_momentum
                self.record_outcome(report, "alert" if sent else "filtered")
                if sent:
                    header = "🔥 Fomo'da yükselen token" if job.from_fomo else "🆕 Yeni havuz"
                    await self.broadcast(format_report(report, self.settings.blockscout_url, header))
                    if self.settings.followup_min > 0 or self.settings.exit_checks_min:
                        task = asyncio.create_task(self.watch(report))
                        self.followups.add(task)
                        task.add_done_callback(self.followups.discard)
            except Exception:
                log.exception("analysis failed for %s", job.token)
            finally:
                self.queue.task_done()

    def alert_snapshot(self, report: dict) -> Snapshot:
        market = report.get("market") or {}
        creator = ((report.get("launch") or {}).get("creator") or "").lower()
        return Snapshot(
            dev_pct=(report.get("launch") or {}).get("dev_pct"),
            # the dev is watched on its own; don't report the same sale twice
            top_wallets={w: p for w, p in ((report.get("holders") or {}).get("top_wallets") or {}).items() if w != creator},
            liquidity_base=market.get("liquidity_base"),
            liquidity_quote=market.get("liquidity_quote"),
            price_usd=float(market["price_usd"]) if market.get("price_usd") else None,
        )

    async def current_snapshot(self, report: dict, then: Snapshot) -> tuple[Snapshot, dict]:
        token, supply = report["token"], report.get("total_supply") or 0

        async def share(wallet: str) -> float | None:
            balance = await self.rpc.try_call_fn(token, "balanceOf(address)", ["uint256"], ["address"], [wallet])
            return 100.0 * balance[0] / supply if balance and supply else None

        creator = (report.get("launch") or {}).get("creator")
        pairs = await self.analyzer.dexscreener.token_pairs(token) if self.analyzer.dexscreener else []
        market = market_summary(pairs, (report.get("pool") or {}).get("pool"))
        now = Snapshot(
            dev_pct=await share(creator) if creator and then.dev_pct is not None else None,
            top_wallets={w: pct for w in then.top_wallets if (pct := await share(w)) is not None},
            liquidity_base=market.get("liquidity_base"),
            liquidity_quote=market.get("liquidity_quote"),
            price_usd=float(market["price_usd"]) if market.get("price_usd") else None,
        )
        return now, market

    async def watch(self, report: dict):
        """After an alert: send 🔴 ÇIK / 🟠 DİKKAT when who-is-selling says so, plus one follow-up.

        A falling price alone never triggers an exit (see exits.py)."""
        token = report["token"]
        then = self.alert_snapshot(report)
        checks = sorted({*self.settings.exit_checks_min, *([self.settings.followup_min] if self.settings.followup_min > 0 else [])})
        sent_level, elapsed = None, 0.0
        for minute in checks:
            await asyncio.sleep((minute - elapsed) * 60)
            elapsed = minute
            try:
                now, market = await self.current_snapshot(report, then)
                reasons = evaluate_exit(
                    then, now, self.tracker.stats(token, 300),
                    {"buys": market.get("buys_m5"), "sells": market.get("sells_m5")},
                )
                level = exit_level(reasons)
                escalated = level and (sent_level is None or (sent_level == WARNING and level == STRONG))
                if escalated and self.alerts_on:
                    await self.broadcast(format_exit(report, reasons, level, market, minute))
                    self.outcomes.record(token, "exit" if level == STRONG else "caution",
                                         features={"reasons": [r for _, r in reasons], "minute": minute})
                    sent_level = level
                    if level == STRONG:
                        return  # told to get out: stop watching
                elif minute == self.settings.followup_min and self.alerts_on:
                    recent = self.tracker.stats(token, minute * 60)
                    sellers_hour = self.tracker.stats(token, 3600)["sellers"]
                    await self.broadcast(format_followup(report, recent, sellers_hour, market, minute, reasons))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("exit check failed for %s", token)

    async def wallet_loop(self):
        while True:
            try:
                self.wallets.refresh()
            except Exception:
                log.exception("smart wallet refresh failed")
            await asyncio.sleep(600)

    async def launch_loop(self):
        """Keeps the local Pons launch index (deployer history) current; backfills a little each round."""
        index = self.analyzer.launches
        while True:
            try:
                if await index.sync(self.rpc) > 1:
                    log.info("Pons launch index: %d launches", index.count())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Pons launch index sync failed: %s", exc)
            await asyncio.sleep(30)

    async def broadcast(self, text: str):
        for chat_id in self.settings.telegram_chat_ids:
            try:
                await self.app.bot.send_message(
                    chat_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
                )
            except Exception:
                log.exception("could not send alert to %s", chat_id)

    async def symbol(self, token: str) -> str:
        if token not in self.symbols:
            result = await self.rpc.try_call_fn(token, "symbol()", ["string"])
            self.symbols[token] = result[0] if result else token[:8]
        return self.symbols[token]

    # --- commands ---
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if not self._authorized(update):
            await update.message.reply_text(
                f"Bu bot özeldir. Sohbet ID'niz: {chat_id}\n"
                "Botu kullanmak için bu ID'yi .env dosyasındaki TELEGRAM_CHAT_IDS alanına ekleyin."
            )
            return
        await update.message.reply_html(HELP + f"\nSohbet ID: <code>{chat_id}</code>")

    async def cmd_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Kullanım: /check 0x...")
            return
        msg = await update.message.reply_text("🔍 Analiz ediliyor...")
        try:
            token = context.args[0]
            report = await self.analyzer.analyze(token, fomo=self.fomo_stats(token))
            self.attach_momentum(report)
            text = format_report(report, self.settings.blockscout_url)
        except ValueError as exc:
            text = f"❌ {exc}"
        except Exception:
            log.exception("check failed")
            text = "❌ Analiz sırasında hata oluştu, biraz sonra tekrar deneyin."
        await msg.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    async def cmd_trend(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        window = 15 * 60
        rows = self.tracker.top(window, limit=10)
        if not rows:
            await update.message.reply_text("Henüz Fomo işlemi görülmedi, biraz bekleyin.")
            return
        lines = ["📱 <b>Fomo'da son 15 dk en çok alınanlar</b> (Robinhood Chain)", ""]
        for i, (token, s) in enumerate(rows, 1):
            lines.append(
                f"{i}. <b>{escape(await self.symbol(token))}</b> — {s['buyers']} alıcı / {s['sellers']} satıcı · "
                f"${s['buy_usd']:,.0f}\n    <code>{token}</code>"
            )
        lines.append("\nDetay için: /check &lt;adres&gt;")
        await update.message.reply_html("\n".join(lines))

    async def cmd_scorecard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        hours = float(context.args[0]) if context.args and context.args[0].replace(".", "", 1).isdigit() else 24.0
        results = self.outcomes.results(hours)
        by_kind = {k: [r for r in results if r["kind"] == k]
                   for k in ("alert", "filtered", "shadow", "pons", "pons_junk", "pons_early", "pons_early_junk",
                             "exit", "caution")}
        groups = [
            ("🔔 Bildirim gidenler", summarize(by_kind["alert"])),
            ("🚫 Filtreye takılanlar", summarize(by_kind["filtered"])),
            ("👤 Gölge grup", summarize(by_kind["shadow"])),
            (f"🐣 Pons {self.settings.pons_min_buyers}+ alıcı (ön filtreden geçen)", summarize(by_kind["pons"])),
            (f"🗑️ Pons {self.settings.pons_min_buyers}+ alıcı (çöp sayılan)", summarize(by_kind["pons_junk"])),
            (f"🐣 Pons {self.settings.pons_early_min_buyers}+ alıcı, erken (ön filtreden geçen)",
             summarize(by_kind["pons_early"])),
            (f"🗑️ Pons {self.settings.pons_early_min_buyers}+ alıcı, erken (çöp sayılan)",
             summarize(by_kind["pons_early_junk"])),
        ]
        for bucket in ("🚀 70+", "🟡 45-69", "🧊 <45"):
            groups.append((f"Momentum {bucket} (tüm gruplar)",
                           summarize([r for r in results if momentum_bucket(r["momentum"]) == bucket])))
        analysed = by_kind["alert"] + by_kind["filtered"]
        for bucket in ("✅ 70+", "⚠️ 50-69", "🔸 30-49", "⛔ <30"):
            groups.append((f"Güven {bucket} (analiz edilenler)",
                           summarize([r for r in analysed if trust_bucket(r["trust"]) == bucket])))
        for bucket in ("🚀 70+", "🟡 45-69", "🧊 <45"):
            groups.append((f"Bildirim gidenler, momentum {bucket}",
                           summarize([r for r in by_kind["alert"] if momentum_bucket(r["momentum"]) == bucket])))
        exits = [("🔴 ÇIK", summarize_exits(by_kind["exit"])), ("🟠 DİKKAT", summarize_exits(by_kind["caution"]))]
        for text in format_scorecard(hours, groups, exits):
            await update.message.reply_html(text)

    async def cmd_findings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        args = context.args or []
        hours = float(args[0]) if args and args[0].replace(".", "", 1).isdigit() else 72.0
        words = [a.lower() for a in args]
        kinds = (("pons_early", "pons_early_junk") if "erken" in words else ("pons", "pons_junk") if "pons" in words
                 else ("alert", "filtered"))
        results = [r for r in self.outcomes.results(hours) if r["kind"] in kinds]
        await update.message.reply_html(
            format_findings(hours, summarize(results), finding_table(results, kinds=kinds)[:25],
                            pons=kinds[0].startswith("pons"))
        )

    async def cmd_position(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        try:
            amount = float(context.args[0].replace(",", ".")) if context.args else None
        except ValueError:
            amount = None
        if not amount or amount <= 0:
            be = breakeven_multiple(self.position_usd, self.settings.fomo_fee_pct, self.settings.fomo_fee_min_usd)
            await update.message.reply_text(f"Kullanım: /pozisyon 5 (şu an: ${self.position_usd:g}, başa baş {be}x)")
            return
        self.storage.set_state("position_usd", str(amount))
        lines = [f"✅ Pozisyon: ${amount:g}", "", "Komisyonla başa baş (alım + satım):"]
        for size in sorted({3.0, 5.0, 10.0, 20.0, 50.0, amount}):
            be = breakeven_multiple(size, self.settings.fomo_fee_pct, self.settings.fomo_fee_min_usd)
            mark = " ◀" if size == amount else ""
            lines.append(f"  ${size:g} → {be}x" if be else f"  ${size:g} → komisyonu karşılamıyor")
            lines[-1] += mark
        await update.message.reply_text("\n".join(lines))

    async def cmd_smart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        top = self.wallets.top(10)
        if not top:
            await update.message.reply_text("Henüz yeterli veri yok: akıllı cüzdanlar birkaç saatlik işlemden sonra belirir.")
            return
        lines = [f"🧠 <b>Akıllı Fomo cüzdanları</b> (son 7 gün, {len(self.wallets.smart)} cüzdan)", ""]
        for i, s in enumerate(top, 1):
            lines.append(f"{i}. <code>{s.wallet}</code>\n    {s.closed} işlem · kazanma %{s.win_rate * 100:.0f} · kâr ${s.pnl_usd:,.0f}")
        await update.message.reply_html("\n".join(lines))

    async def cmd_min_score(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        if not context.args or not context.args[0].isdigit() or not 0 <= int(context.args[0]) <= 100:
            await update.message.reply_text(f"Kullanım: /minskor 0-100 (şu an: {self.min_score})")
            return
        self.storage.set_state("min_score", context.args[0])
        await update.message.reply_text(f"✅ Artık sadece skoru {context.args[0]} ve üstü olanlar bildirilecek.")

    async def cmd_min_momentum(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        if not context.args or not context.args[0].isdigit() or not 0 <= int(context.args[0]) <= 100:
            await update.message.reply_text(f"Kullanım: /minmomentum 0-100 (şu an: {self.min_momentum}, 0 = kapalı)")
            return
        self.storage.set_state("min_momentum", context.args[0])
        await update.message.reply_text(f"✅ Artık sadece momentumu {context.args[0]} ve üstü olanlar bildirilecek.")

    async def cmd_min_buyers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        if not context.args or not context.args[0].isdigit() or int(context.args[0]) < 1:
            await update.message.reply_text(f"Kullanım: /minalici 1+ (şu an: {self.min_buyers})")
            return
        self.storage.set_state("min_buyers", context.args[0])
        await update.message.reply_text(
            f"✅ Bir coin {self.settings.fomo_window_min:g} dakikada en az {context.args[0]} farklı "
            "Fomo kullanıcısı tarafından alınınca analiz edilecek."
        )

    async def cmd_min_usd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        if not context.args or not context.args[0].isdigit():
            await update.message.reply_text(f"Kullanım: /minhacim 500 (şu an: ${self.min_buy_usd:,.0f})")
            return
        self.storage.set_state("min_buy_usd", context.args[0])
        await update.message.reply_text(
            f"✅ Bir coin {self.settings.fomo_window_min:g} dakikada Fomo'dan en az ${int(context.args[0]):,} "
            "alım görünce analiz edilecek."
        )

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._authorized(update):
            self.storage.set_state("alerts_on", "0")
            await update.message.reply_text("⏸ Otomatik bildirimler durduruldu. /check ve /trend çalışmaya devam eder.")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._authorized(update):
            self.storage.set_state("alerts_on", "1")
            await update.message.reply_text("▶️ Otomatik bildirimler açıldı.")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        await update.message.reply_text(
            f"Fomo son blok: {self.storage.get_state('fomo_last_block', '-')}\n"
            f"RPC: {self.rpc.url.split('//')[-1]}\n"
            f"Fomo'da izlenen coin (son 1 saat): {len(self.tracker.trades)}\n"
            f"Analiz kuyruğu: {self.queue.qsize()}\n"
            f"Pons lansman indeksi: {self.analyzer.launches.count():,} coin\n"
            f"Pons curve'ünde işlem gören (son {self.settings.pons_max_age_min:g} dk): {len(self.pons.trades)} coin\n"
            f"Bildirimler: {'açık' if self.alerts_on else 'kapalı'} · Min. skor: {self.min_score} · "
            f"Min. momentum: {self.min_momentum} · "
            f"Min. alıcı: {self.min_buyers} · Min. hacim: ${self.min_buy_usd:,.0f} / {self.settings.fomo_window_min:g} dk"
        )

    # --- lifecycle ---
    async def _post_init(self, app: Application):
        if self.settings.enable_fomo_watcher:
            watcher = FomoWatcher(self.rpc, self.settings, self.storage, self.tracker)
            self.tasks.append(asyncio.create_task(watcher.run(self.on_fomo_trades)))
        if self.settings.enable_fomo_watcher:
            self.tasks.append(asyncio.create_task(REGISTRY.run(self.rpc, self.settings.v4_pool_manager)))
        if self.settings.enable_pons_watcher and self.analyzer.launches:
            watcher = PonsWatcher(self.rpc, self.settings, self.storage, self.pons)
            self.tasks.append(asyncio.create_task(watcher.run(self.on_pons_trades)))
        if self.settings.enable_pool_watcher:
            watcher = PoolWatcher(self.rpc, self.settings, self.storage)
            self.tasks.append(asyncio.create_task(watcher.run(self.on_pool)))
        self.tasks.append(asyncio.create_task(self.outcome_loop()))
        self.tasks.append(asyncio.create_task(self.wallet_loop()))
        self.tasks.append(asyncio.create_task(self.launch_loop()))
        for _ in range(self.settings.analysis_workers):
            self.tasks.append(asyncio.create_task(self.worker()))

    async def _post_shutdown(self, app: Application):
        for task in [*self.tasks, *self.followups]:
            task.cancel()
        await asyncio.gather(*self.tasks, *self.followups, return_exceptions=True)
        await self.rpc.close()
        await self.http.aclose()
        self.storage.close()

    def run(self):
        if not self.settings.telegram_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN tanımlı değil (.env dosyasını kontrol edin)")
        self.app = (
            Application.builder()
            .token(self.settings.telegram_token)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )
        self.app.add_handler(CommandHandler(["start", "help", "yardim"], self.cmd_start))
        self.app.add_handler(CommandHandler("check", self.cmd_check))
        self.app.add_handler(CommandHandler("trend", self.cmd_trend))
        self.app.add_handler(CommandHandler("karne", self.cmd_scorecard))
        self.app.add_handler(CommandHandler("pozisyon", self.cmd_position))
        self.app.add_handler(CommandHandler("akilli", self.cmd_smart))
        self.app.add_handler(CommandHandler("minskor", self.cmd_min_score))
        self.app.add_handler(CommandHandler("minmomentum", self.cmd_min_momentum))
        self.app.add_handler(CommandHandler("bulgular", self.cmd_findings))
        self.app.add_handler(CommandHandler("minalici", self.cmd_min_buyers))
        self.app.add_handler(CommandHandler("minhacim", self.cmd_min_usd))
        self.app.add_handler(CommandHandler("durdur", self.cmd_pause))
        self.app.add_handler(CommandHandler("devam", self.cmd_resume))
        self.app.add_handler(CommandHandler("durum", self.cmd_status))
        self.app.run_polling()


def _pool_dict(pool: NewPool) -> dict:
    return {
        "dex": pool.dex, "pool": pool.pool, "token": pool.token, "quote": pool.quote,
        "factory": pool.factory, "hooks": pool.hooks,
    }
