"""Telegram bot: pushes alerts for tokens rising on Fomo and answers /check requests."""

import asyncio
import logging
from dataclasses import dataclass
from html import escape

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from .analyzer import Analyzer
from .config import Settings
from .discovery import NewPool, PoolWatcher
from .fomo import FomoTrade, FomoTracker, FomoWatcher
from .report import format_report
from .rpc import RpcClient
from .sources import Blockscout, DexScreener
from .storage import Storage

log = logging.getLogger(__name__)

HELP = (
    "🤖 <b>Robinhood Chain · Fomo Token Tarayıcı</b>\n\n"
    "Fomo kullanıcılarının Robinhood Chain'de aldığı coinleri canlı izler. Bir coini kısa sürede "
    "yeterince farklı kişi alınca güvenlik taraması yapıp sonucu gönderir.\n\n"
    "/trend — şu an Fomo'da en çok alınan coinler\n"
    "/check &lt;adres&gt; — bir token'ı hemen analiz et\n"
    "/minskor &lt;0-100&gt; — bu skorun altındakiler için bildirim gönderme\n"
    "/minalici &lt;sayı&gt; — bildirim için gereken farklı Fomo alıcısı sayısı\n"
    "/durdur — otomatik bildirimleri durdur\n"
    "/devam — otomatik bildirimleri aç\n"
    "/durum — tarayıcı durumu\n"
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
        self.symbols: dict[str, str] = {}
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []
        self.app: Application | None = None

    # --- settings kept in the database so they survive restarts ---
    @property
    def min_score(self) -> int:
        return int(self.storage.get_state("min_score", str(self.settings.min_score_alert)))

    @property
    def min_buyers(self) -> int:
        return int(self.storage.get_state("min_buyers", str(self.settings.fomo_min_buyers)))

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
        for token in {t.token for t in trades if t.side == "buy"}:
            stats = self.tracker.stats(token, self.fomo_window)
            if stats["buyers"] >= self.min_buyers and self.storage.mark_alerted(token):
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
                self.storage.save_report(job.token, report["score"], report)
                if self.alerts_on and report["score"] >= self.min_score:
                    header = "🔥 Fomo'da yükselen token" if job.from_fomo else "🆕 Yeni havuz"
                    await self.broadcast(format_report(report, self.settings.blockscout_url, header))
            except Exception:
                log.exception("analysis failed for %s", job.token)
            finally:
                self.queue.task_done()

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

    async def cmd_min_score(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        if not context.args or not context.args[0].isdigit() or not 0 <= int(context.args[0]) <= 100:
            await update.message.reply_text(f"Kullanım: /minskor 0-100 (şu an: {self.min_score})")
            return
        self.storage.set_state("min_score", context.args[0])
        await update.message.reply_text(f"✅ Artık sadece skoru {context.args[0]} ve üstü olanlar bildirilecek.")

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
            f"Bildirimler: {'açık' if self.alerts_on else 'kapalı'} · Min. skor: {self.min_score} · "
            f"Min. alıcı: {self.min_buyers}/{self.settings.fomo_window_min:g} dk"
        )

    # --- lifecycle ---
    async def _post_init(self, app: Application):
        if self.settings.enable_fomo_watcher:
            watcher = FomoWatcher(self.rpc, self.settings, self.storage, self.tracker)
            self.tasks.append(asyncio.create_task(watcher.run(self.on_fomo_trades)))
        if self.settings.enable_pool_watcher:
            watcher = PoolWatcher(self.rpc, self.settings, self.storage)
            self.tasks.append(asyncio.create_task(watcher.run(self.on_pool)))
        for _ in range(self.settings.analysis_workers):
            self.tasks.append(asyncio.create_task(self.worker()))

    async def _post_shutdown(self, app: Application):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
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
        self.app.add_handler(CommandHandler("minskor", self.cmd_min_score))
        self.app.add_handler(CommandHandler("minalici", self.cmd_min_buyers))
        self.app.add_handler(CommandHandler("durdur", self.cmd_pause))
        self.app.add_handler(CommandHandler("devam", self.cmd_resume))
        self.app.add_handler(CommandHandler("durum", self.cmd_status))
        self.app.run_polling()


def _pool_dict(pool: NewPool) -> dict:
    return {
        "dex": pool.dex, "pool": pool.pool, "token": pool.token, "quote": pool.quote,
        "factory": pool.factory, "hooks": pool.hooks,
    }
