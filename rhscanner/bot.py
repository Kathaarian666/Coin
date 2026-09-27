"""Telegram bot: pushes alerts for tokens rising on Fomo and answers /check requests."""

import asyncio
import logging
import time
from dataclasses import dataclass
from html import escape

import httpx
from eth_utils import to_checksum_address
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
from .outcomes import EARLY_MOMENTUM_STEPS, OutcomeLog, early_entry, backtest, early_entry_candidates, rug_filter_sweep, rug_risk_of, lower_bar_candidates, parameter_sweep, feature_table, finding_table, momentum_bucket, summarize, summarize_exits, trust_bucket
from .pons import PonsTracker, PonsWatcher, detect_signals, eth_usd_price, pons_tiers
from .report import (format_analysis, format_backtest, format_exit, format_findings, format_followup,
                     format_report, format_scorecard, format_signal, format_strategies, format_sweep,
                     format_winners)
from .rpc import RpcClient
from .sources import Blockscout, DexScreener
from .rugrisk import rug_bucket, rug_risk
from .storage import Storage
from .strategy import simulate
from .wallets import WalletBook
from .winners import GeckoTerminal, find_winners

log = logging.getLogger(__name__)

TEST_POSITION_USD = 100.0  # tests measure the signals, not position sizing: a size where the fee floor barely matters
WAVE_MIN_AGE = 3600  # a second wave comes at least an hour after the coin's first signal...
WAVE_MAX_AGE = 3 * 86400  # ...and within three days

HELP = (
    "🤖 <b>Robinhood Chain · Fomo Token Tarayıcı</b>\n\n"
    "Fomo kullanıcılarının Robinhood Chain'de aldığı coinleri canlı izler. Bir coini kısa sürede "
    "yeterince farklı kişi alınca güvenlik taraması yapıp sonucu gönderir.\n\n"
    "/trend — şu an Fomo'da en çok alınan coinler\n"
    "/check &lt;adres&gt; — bir token'ı hemen analiz et\n"
    "/minskor &lt;0-100&gt; — bu skorun altındakiler için bildirim gönderme\n"
    "/minmomentum &lt;0-100&gt; — momentumu bunun altındakiler için bildirim gönderme (0 = kapalı)\n"
    "/erken &lt;momentum&gt;|kapat — alıcı eşiğinden önce ⚡ erken sinyal (büyük, tutulan, sıfırdan başlayan alımlar)\n"
    "/maxrug &lt;1-100&gt;|kapat — rug riski bunun üstündekiler için bildirim gönderme\n"
    "/minalici &lt;sayı&gt; — bildirim için gereken farklı Fomo alıcısı sayısı\n"
    "/minhacim &lt;$&gt; — bildirim için gereken en az Fomo alım hacmi\n"
    "/durdur — otomatik bildirimleri durdur\n"
    "/devam — otomatik bildirimleri aç\n"
    "/durum — tarayıcı durumu\n"
    "/karne [saat] — sinyallerin sonuçları (varsayılan son 24 saat)\n"
    "/bulgular [saat] [pons|erken] — güven bulgularına (veya Pons çöp nedenlerine) göre sonuçlar\n"
    "/analiz [saat] — hangi özellik kazandırıyor (varsayılan son 7 gün)\n"
    "/kazananlar [gün] [kat] — 10x+ yapan coinleri yakaladık mı, ne engelledi (varsayılan 7 gün, 10x)\n"
    "/geritest [saat] — yeni momentum puanını (v2) geçmiş sinyallerde eskisiyle karşılaştır\n"
    "/momentumv2 ac|kapat — bildirimlerde yeni momentum puanını kullan\n"
    "/sinyal &lt;adres&gt; — bir coin için kaydedilen sinyallerin tüm özellikleri ve sonucu\n"
    "/tarama [saat] — min momentum × min güven kombinasyonlarının isabeti ve yakalaması\n"
    "/strateji [saat] — çıkış kurallarını geçmiş bildirimlerde dene (sabit $100 test tutarı)\n"
    "/pozisyon &lt;$&gt; — işlem tutarınız (komisyonla başa baş hesabı için)\n"
    "/akilli — kazanma oranı yüksek Fomo cüzdanları\n"
)


@dataclass
class Job:
    token: str
    pool: dict | None = None
    from_fomo: bool = False
    delay: float = 0.0
    early: bool = False  # early-entry rule A under the buyer bar: needs /erken momentum


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
        self.decimals: dict[str, int] = {}  # from analysed reports; Fomo prices assume 18 otherwise
        self.early_checked: set[str] = set()
        self.waves_seen: set[str] = {row[0] for row in self.storage.db.execute(
            "SELECT token FROM signals WHERE kind = 'wave2'")}
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
    def max_rug(self) -> int:
        """Alerts need a rug risk below this; 101 = off."""
        return int(self.storage.get_state("max_rug", "101"))

    @property
    def early_momentum(self) -> int:
        """Momentum an early-entry alert needs (0 = early alerts off)."""
        return int(self.storage.get_state("early_momentum", "0"))

    @property
    def momentum_v2(self) -> bool:
        return self.storage.get_state("momentum_v2", "0") == "1"

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
            if rising and not warmup:
                self.check_second_wave(token)
            if not rising and not warmup:
                await self.check_early_entry(token)
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
        return pons_tiers(self.settings)

    async def on_pons_trades(self, trades, warmup: bool = False):
        """A young Pons coin that enough wallets are buying on its curve: recorded for /karne (no alert)."""
        if warmup or not self.eth_usd:
            return
        for token, kind, features in detect_signals(
            self.pons, self.analyzer.launches, trades, self.pons_tiers(), self.settings.pons_max_age_min,
            self.fomo_window, self.eth_usd, self.pons_seen,
        ):
            self.outcomes.record(token, kind, features=features, pair=None)
            log.info("Pons signal %s %s: %s", kind, token, features)

    def fallback_price(self, token: str) -> float | None:
        """USD price when DexScreener does not list the coin yet: its latest Fomo trade, else its Pons curve."""
        per_unit = self.tracker.last_price(token)
        if per_unit:
            return per_unit * 10 ** self.decimals.get(token.lower(), 18)
        return self.pons_price(token)

    def pons_price(self, token: str) -> float | None:
        """USD price of a coin still on its Pons curve (last trade), for outcome sampling."""
        curve = self.analyzer.launches.curve_of(token) if self.analyzer.launches else None
        price = self.pons.price(curve) if curve else None
        return price * self.eth_usd if price and self.eth_usd else None

    async def refresh_eth_usd(self):
        if time.time() - self.eth_usd_at < 600 or not self.analyzer.dexscreener:
            return
        price = await eth_usd_price(self.analyzer.dexscreener, self.settings.weth)
        if price:
            self.eth_usd, self.eth_usd_at = price, time.time()

    async def check_early_entry(self, token: str):
        """Rule A (few large buys from nothing, all held) under the buyer bar: analyse now instead of waiting for
        the bar; the worker alerts only at /erken momentum. /geritest: A at momentum 85+ held 5x 45% (11 in a week)."""
        key = token.lower()
        if not self.early_momentum or key in self.early_checked:
            return
        if self.tracker.stats(token, 300)["buyers"] < 5 or self.storage.was_alerted(key):
            return  # cheap checks first: this runs for every coin bought, every poll
        if early_entry(fomo_features(self.tracker, token), "A"):
            self.early_checked.add(key)
            log.info("%s matches the early-entry rule; analysing", token)
            await self.queue.put(Job(token, from_fomo=True, early=True))

    def check_second_wave(self, token: str):
        """A coin signalled an hour or more ago that went quiet and is being bought hard again: measured as
        `wave2` (no alert yet). Quiet = under half the buyer bar 30-60 minutes ago."""
        key = token.lower()
        if key in self.waves_seen:
            return
        now = time.time()
        first = next(iter(self.outcomes.signals_for(key, ("alert", "filtered", "shadow"))), None)
        if not first or not WAVE_MIN_AGE <= now - first["ts"] <= WAVE_MAX_AGE:
            return
        if self.tracker.buyers_between(key, 3600, 1800, now) >= self.min_buyers / 2:
            return  # never cooled off: the same wave
        self.waves_seen.add(key)
        task = asyncio.create_task(self.record_second_wave(token, first))
        self.followups.add(task)
        task.add_done_callback(self.followups.discard)

    async def record_second_wave(self, token: str, first: dict):
        try:
            pairs = await self.analyzer.dexscreener.token_pairs(token) if self.analyzer.dexscreener else []
            market = market_summary(pairs, None)
            fomo = fomo_features(self.tracker, token)
            fomo["smart_buyers_10m"] = len(self.wallets.smart_buyers(self.tracker, token))
            fomo["churn_share_30m"] = fomo_churn(self.tracker, token)
            score, reasons, extra = momentum_score(fomo, market, None, v2=True)
            price = float(market["price_usd"]) if market.get("price_usd") else None
            features = {
                **fomo, **extra, "liquidity_usd": market.get("liquidity_usd"), "fdv": market.get("fdv"),
                "socials": market.get("socials"), "first_kind": first["kind"],
                "hours_since_first": round((time.time() - first["ts"]) / 3600, 1),
                "price_vs_first": round(price / first["p0"], 3) if price and first.get("p0") else None,
            }
            self.outcomes.record(token, "wave2", momentum=score, features=features)
            log.info("second wave %s: momentum %s, %s", token, score, features)
        except Exception:
            log.exception("second wave check failed for %s", token)

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
        market, launch = report.get("market") or {}, report.get("launch")
        v1, reasons1, extra = momentum_score(features, market, launch)
        v2, reasons2, _ = momentum_score(features, market, launch, v2=True)
        score, reasons = (v2, reasons2) if self.momentum_v2 else (v1, reasons1)
        risk, risk_reasons = rug_risk({**features, **extra})
        report["rug_risk"] = {"score": risk, "reasons": risk_reasons}
        report["momentum"] = {"score": score, "reasons": reasons,
                              "features": {**features, **extra, "momentum_v1": v1, "momentum_v2": v2,
                                           "rug_risk": risk}}

    def shadow_momentum(self, features: dict, pairs: list[dict], pair_address: str | None) -> tuple[int, dict]:
        market = market_summary(pairs, pair_address)
        v1, _, extra = momentum_score(features, market)
        v2, _, _ = momentum_score(features, market, v2=True)
        return (v2 if self.momentum_v2 else v1), {
            **extra, "liquidity_usd": market.get("liquidity_usd"), "fdv": market.get("fdv"),
            "socials": market.get("socials"), "momentum_v1": v1, "momentum_v2": v2,
        }

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
            "early": bool(report.get("early")),
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
                                                       price_fn=self.fallback_price)
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
                self.decimals[job.token.lower()] = report.get("decimals", 18)
                self.storage.save_report(job.token, report["score"], report)
                momentum = (report.get("momentum") or {}).get("score") or 0
                risk = (report.get("rug_risk") or {}).get("score") or 0
                bar = max(self.min_momentum, self.early_momentum) if job.early else self.min_momentum
                sent = (self.alerts_on and report["score"] >= self.min_score and momentum >= bar
                        and risk < self.max_rug)
                if job.early:
                    # an early check that fails leaves the coin to the normal buyer bar; one that passes claims it
                    if not sent or not self.storage.mark_alerted(job.token):
                        continue
                    report["early"] = True
                self.record_outcome(report, "alert" if sent else "filtered")
                if sent:
                    header = ("⚡ Erken sinyal (alım sıfırdan başladı, büyük ve tutulan alımlar)" if job.early
                              else "🔥 Fomo'da yükselen token" if job.from_fomo else "🆕 Yeni havuz")
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
                   for k in ("alert", "filtered", "shadow", "wave2", "pons", "pons_junk", "pons_early",
                             "pons_early_junk", "exit", "caution")}
        groups = [
            ("🔔 Bildirim gidenler", summarize(by_kind["alert"])),
            ("🚫 Filtreye takılanlar", summarize(by_kind["filtered"])),
            ("👤 Gölge grup", summarize(by_kind["shadow"])),
            ("⚡ Erken bildirimler", summarize([r for r in by_kind["alert"] if (r.get("features") or {}).get("early")])),
            ("🔁 İkinci dalga (ölçüm, bildirim yok)", summarize(by_kind["wave2"])),
        ]
        for bucket in ("🚀 70+", "🟡 45-69"):
            groups.append((f"🔁 İkinci dalga, momentum {bucket}",
                           summarize([r for r in by_kind["wave2"] if momentum_bucket(r["momentum"]) == bucket])))
        if any(by_kind[k] for k in ("pons", "pons_junk", "pons_early", "pons_early_junk")):
            groups += [
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
        for bucket in ("🟢 düşük (<20)", "🟡 orta (20-59)", "🔴 yüksek (60+)"):
            groups.append((f"Bildirim gidenler, rug riski {bucket}",
                           summarize([r for r in by_kind["alert"] if rug_bucket(rug_risk_of(r)) == bucket])))
        for bucket in ("🚀 70+", "🟡 45-69", "🧊 <45"):
            groups.append((f"Bildirim gidenler, momentum {bucket}",
                           summarize([r for r in by_kind["alert"] if momentum_bucket(r["momentum"]) == bucket])))
        exits = [("🔴 ÇIK", summarize_exits(by_kind["exit"])), ("🟠 DİKKAT", summarize_exits(by_kind["caution"]))]
        for text in format_scorecard(hours, groups, exits, self.outcomes.unmeasured(hours)):
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

    async def cmd_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        hours = float(context.args[0]) if context.args and context.args[0].replace(".", "", 1).isdigit() else 168.0
        results = [r for r in self.outcomes.results(hours) if r["kind"] in ("alert", "filtered", "shadow")]
        for text in format_analysis(hours, len(results), feature_table(results)):
            await update.message.reply_html(text)

    async def cmd_winners(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        numbers = [float(a) for a in (context.args or []) if a.replace(".", "", 1).isdigit()]
        days = numbers[0] if numbers else 7.0
        multiple = numbers[1] if len(numbers) > 1 else 10.0
        await update.message.reply_text(
            f"⏳ Son {days:g} günde {multiple:g}x yapan coinler aranıyor (GeckoTerminal yavaş, en fazla ~8 dk)...")
        try:
            winners, checked, candidates = await find_winners(GeckoTerminal(self.http), self.outcomes, days, multiple)
        except Exception:
            log.exception("winner autopsy failed")
            await update.message.reply_text("Kazanan listesi alınamadı (GeckoTerminal), biraz sonra tekrar deneyin.")
            return
        bars = {"min_score": self.min_score, "min_momentum": self.min_momentum, "min_buyers": self.min_buyers,
                "min_buy_usd": self.min_buy_usd, "max_rug": self.max_rug}
        try:
            for text in format_winners(days, multiple, winners, checked, bars, candidates):
                await update.message.reply_html(text)
        except Exception as exc:
            log.exception("winner report failed")
            await update.message.reply_text(f"Kazanan raporu gönderilemedi ({exc.__class__.__name__}: {exc})"[:500])

    async def cmd_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        token = (context.args or [""])[0].lower()
        if not (token.startswith("0x") and len(token) == 42):
            await update.message.reply_text("Kullanım: /sinyal 0x...  (coinin adresi)")
            return
        signals = self.outcomes.signals_for(token, ("alert", "filtered", "shadow", "wave2", "exit", "caution"))
        outcome = {r["kind"]: r for r in self.outcomes.results(24 * 30) if r["token"] == token}
        await update.message.reply_html(format_signal(await self.symbol(to_checksum_address(token)), signals, outcome))

    async def cmd_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        hours = float(context.args[0]) if context.args and context.args[0].replace(".", "", 1).isdigit() else 168.0
        everything = self.outcomes.results(hours)
        results = [r for r in everything if r["kind"] in ("alert", "filtered")]
        halves = backtest(results, self.min_score, self.min_momentum)
        lower = lower_bar_candidates([r for r in everything if r["kind"] == "shadow"], self.min_buyers,
                                     self.min_momentum)
        early = {(rule, m): early_entry_candidates(everything, self.min_buyers, rule, m)
                 for rule in ("A", "B") for m in EARLY_MOMENTUM_STEPS}
        for text in format_backtest(hours, self.min_score, self.min_momentum, halves, self.momentum_v2,
                                    lower, self.min_buyers, early):
            await update.message.reply_html(text)

    async def cmd_momentum_v2(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        arg = (context.args or [""])[0].lower()
        if arg not in ("ac", "aç", "kapat"):
            await update.message.reply_text(
                f"Kullanım: /momentumv2 ac | kapat (şu an: {'açık' if self.momentum_v2 else 'kapalı'})")
            return
        self.storage.set_state("momentum_v2", "0" if arg == "kapat" else "1")
        await update.message.reply_text(
            "✅ Yeni momentum puanı (v2) kullanılıyor." if arg != "kapat" else "✅ Eski momentum puanına (v1) dönüldü.")

    async def cmd_sweep(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        hours = float(context.args[0]) if context.args and context.args[0].replace(".", "", 1).isdigit() else 168.0
        results = [r for r in self.outcomes.results(hours) if r["kind"] in ("alert", "filtered")]
        winners = sum(1 for r in results if (r.get("held_all") or 0) >= 5)
        rows = parameter_sweep(results)
        rug_rows = rug_filter_sweep(results, self.min_momentum, self.min_score)
        for text in format_sweep(hours, len(results), winners, rows, (self.min_momentum, self.min_score), rug_rows):
            await update.message.reply_html(text)

    async def cmd_strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        hours = float(context.args[0]) if context.args and context.args[0].replace(".", "", 1).isdigit() else 168.0
        rows = simulate(self.outcomes.alert_paths(hours), TEST_POSITION_USD, self.settings.fomo_fee_pct,
                        self.settings.fomo_fee_min_usd)
        for text in format_strategies(hours, TEST_POSITION_USD, rows):
            await update.message.reply_html(text)

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

    async def cmd_max_rug(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        arg = (context.args or [""])[0].lower()
        if arg == "kapat":
            self.storage.set_state("max_rug", "101")
            await update.message.reply_text("✅ Rug riski filtresi kapatıldı.")
            return
        if not arg.isdigit() or not 1 <= int(arg) <= 100:
            now = "kapalı" if self.max_rug > 100 else str(self.max_rug)
            await update.message.reply_text(f"Kullanım: /maxrug 1-100 | kapat (şu an: {now})")
            return
        self.storage.set_state("max_rug", arg)
        await update.message.reply_text(f"✅ Rug riski {arg} ve üstü olanlar artık bildirilmeyecek.")

    async def cmd_early(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        arg = (context.args or [""])[0].lower()
        if arg == "kapat":
            self.storage.set_state("early_momentum", "0")
            await update.message.reply_text("✅ Erken sinyaller kapatıldı.")
            return
        if not arg.isdigit() or not 1 <= int(arg) <= 100:
            now = self.early_momentum or "kapalı"
            await update.message.reply_text(f"Kullanım: /erken <momentum 1-100> | kapat (şu an: {now})")
            return
        self.storage.set_state("early_momentum", arg)
        await update.message.reply_text(
            f"✅ Erken sinyaller açık: alım sıfırdan başlayıp alıcı başına ≥$100 ve tutuluyorsa, 10 alıcı beklemeden "
            f"analiz edilir; momentum ≥{arg} ise ⚡ bildirim gider.")

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
            + (f"Pons curve'ünde işlem gören (son {self.settings.pons_max_age_min:g} dk): {len(self.pons.trades)} coin\n"
               if self.settings.enable_pons_watcher else "")
            + f"Bildirimler: {'açık' if self.alerts_on else 'kapalı'} · Min. skor: {self.min_score} · "
            f"Min. momentum: {self.min_momentum} ({'v2' if self.momentum_v2 else 'v1'}) · "
            f"Maks. rug riski: {'kapalı' if self.max_rug > 100 else self.max_rug} · "
            f"Erken sinyal: {('momentum ≥' + str(self.early_momentum)) if self.early_momentum else 'kapalı'} · "
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
        self.app.add_handler(CommandHandler("analiz", self.cmd_analysis))
        self.app.add_handler(CommandHandler("kazananlar", self.cmd_winners, block=False))
        self.app.add_handler(CommandHandler("geritest", self.cmd_backtest))
        self.app.add_handler(CommandHandler("strateji", self.cmd_strategies))
        self.app.add_handler(CommandHandler("tarama", self.cmd_sweep))
        self.app.add_handler(CommandHandler("sinyal", self.cmd_signal))
        self.app.add_handler(CommandHandler("momentumv2", self.cmd_momentum_v2))
        self.app.add_handler(CommandHandler("maxrug", self.cmd_max_rug))
        self.app.add_handler(CommandHandler("erken", self.cmd_early))
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
