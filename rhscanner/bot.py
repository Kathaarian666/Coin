"""Telegram bot: pushes alerts for new tokens and answers /check requests."""

import asyncio
import logging

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from .analyzer import Analyzer
from .config import Settings
from .discovery import NewPool, PoolWatcher
from .report import format_report
from .rpc import RpcClient
from .sources import Blockscout, DexScreener
from .storage import Storage

log = logging.getLogger(__name__)

HELP = (
    "🤖 <b>Robinhood Chain Token Tarayıcı</b>\n\n"
    "Yeni çıkan token'ları tarar; honeypot, vergi, likidite, sahiplik ve cüzdan dağılımını kontrol eder.\n\n"
    "/check &lt;adres&gt; — bir token'ı hemen analiz et\n"
    "/minskor &lt;0-100&gt; — bu skorun altındaki token'lar için bildirim gönderme\n"
    "/durdur — otomatik bildirimleri durdur\n"
    "/devam — otomatik bildirimleri aç\n"
    "/durum — tarayıcı durumu\n"
)


class ScannerApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.http = httpx.AsyncClient(timeout=20)
        self.rpc = RpcClient(settings.rpc_url, settings.rpc_max_rps)
        self.analyzer = Analyzer(
            self.rpc,
            settings,
            Blockscout(settings.blockscout_url, self.http),
            DexScreener(self.http) if settings.use_dexscreener else None,
            self.storage,
        )
        self.queue: asyncio.Queue[NewPool] = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []
        self.app: Application | None = None

    # --- settings kept in the database so they survive restarts ---
    @property
    def min_score(self) -> int:
        return int(self.storage.get_state("min_score", str(self.settings.min_score_alert)))

    @property
    def alerts_on(self) -> bool:
        return self.storage.get_state("alerts_on", "1") == "1"

    def _authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        return bool(chat) and chat.id in self.settings.telegram_chat_ids

    # --- scanning pipeline ---
    async def on_pool(self, pool: NewPool):
        if self.storage.mark_seen(pool.token, _pool_dict(pool), pool.block):
            log.info("new %s pool for %s (%s)", pool.dex, pool.token, pool.pool)
            await self.queue.put(pool)

    async def worker(self):
        while True:
            pool = await self.queue.get()
            try:
                # Give the explorer a moment to index the token and its first holders.
                await asyncio.sleep(self.settings.analysis_delay)
                report = await self.analyzer.analyze(pool.token, _pool_dict(pool))
                self.storage.save_report(pool.token, report["score"], report)
                if self.alerts_on and report["score"] >= self.min_score:
                    await self.broadcast(format_report(report, self.settings.blockscout_url, new=True))
            except Exception:
                log.exception("analysis failed for %s", pool.token)
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
            report = await self.analyzer.analyze(context.args[0])
            text = format_report(report, self.settings.blockscout_url)
        except ValueError as exc:
            text = f"❌ {exc}"
        except Exception:
            log.exception("check failed")
            text = "❌ Analiz sırasında hata oluştu, biraz sonra tekrar deneyin."
        await msg.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    async def cmd_min_score(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        if not context.args or not context.args[0].isdigit() or not 0 <= int(context.args[0]) <= 100:
            await update.message.reply_text(f"Kullanım: /minskor 0-100 (şu an: {self.min_score})")
            return
        self.storage.set_state("min_score", context.args[0])
        await update.message.reply_text(f"✅ Artık sadece skoru {context.args[0]} ve üstü olanlar bildirilecek.")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._authorized(update):
            self.storage.set_state("alerts_on", "0")
            await update.message.reply_text("⏸ Otomatik bildirimler durduruldu. /check çalışmaya devam eder.")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._authorized(update):
            self.storage.set_state("alerts_on", "1")
            await update.message.reply_text("▶️ Otomatik bildirimler açıldı.")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        await update.message.reply_text(
            f"Son taranan blok: {self.storage.get_state('last_block', '-')}\n"
            f"Görülen token: {self.storage.count_tokens()}\n"
            f"Analiz kuyruğu: {self.queue.qsize()}\n"
            f"Bildirimler: {'açık' if self.alerts_on else 'kapalı'} · Min. skor: {self.min_score}"
        )

    # --- lifecycle ---
    async def _post_init(self, app: Application):
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
        self.app.add_handler(CommandHandler("minskor", self.cmd_min_score))
        self.app.add_handler(CommandHandler("durdur", self.cmd_pause))
        self.app.add_handler(CommandHandler("devam", self.cmd_resume))
        self.app.add_handler(CommandHandler("durum", self.cmd_status))
        self.app.run_polling()


def _pool_dict(pool: NewPool) -> dict:
    return {
        "dex": pool.dex, "pool": pool.pool, "token": pool.token, "quote": pool.quote,
        "factory": pool.factory, "hooks": pool.hooks,
    }
