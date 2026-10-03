"""Telegram bot: pushes a safety report for tokens rising on Fomo and answers /check requests."""

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from html import escape

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from .analyzer import Analyzer
from .checks.wash import fomo_churn
from .config import Settings
from .fomo import FomoTrade, FomoTracker, FomoWatcher
from .hooks import REGISTRY
from . import live
from .live import LiveLog
from .report import (format_2x, format_liquidity_warning, format_live_alert, format_paper, format_paper_alert,
                     format_report, format_trust_reply)
from .rpc import RpcClient
from . import paper
from .paper import Book, Follower, Model, PaperLog, Trade
from .sources import Blockscout, DexScreener
from .storage import Storage

log = logging.getLogger(__name__)

HELP = (
    "🤖 <b>Robinhood Chain · Fomo Token Tarayıcı</b>\n\n"
    "Fomo kullanıcılarının Robinhood Chain'de aldığı coinleri canlı izler. Bir coini kısa sürede "
    "yeterince farklı kişi alınca güvenlik taraması yapıp sonucu gönderir.\n\n"
    "/trend — şu an Fomo'da en çok alınan coinler\n"
    "/check &lt;adres&gt; — bir token'ı hemen analiz et\n"
    "/minskor &lt;0-100&gt; — bu güven skorunun altındakiler için bildirim gönderme\n"
    "/minalici &lt;sayı&gt; — bildirim için gereken farklı Fomo alıcısı sayısı\n"
    "/minhacim &lt;$&gt; — bildirim için gereken en az Fomo alım hacmi\n"
    "/durdur — otomatik bildirimleri durdur\n"
    "/devam — otomatik bildirimleri aç\n"
    "/durum — tarayıcı durumu\n"
    "/karne [saat] — kâğıt test: modelin seçtiği coinler ve sanal işlemlerin sonucu (para harcanmaz)\n"
    "/kagitbildirim ac|kapat — kâğıt testin seçtiği her coin için mesaj (varsayılan kapalı)\n"
    "/canli ac|kapat — gerçek bildirim: seçilen coin (satılamayanlar elenir) + güven raporu + 2x / likidite "
    "haberleri (varsayılan kapalı)\n"
)


@dataclass
class Job:
    token: str
    from_fomo: bool = False


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
        # paper test (PROJE.md §2 step 4/5): new coins scored at the 5th Fomo buyer, top 2 % get a virtual trade
        self.paper_model = Model.load()
        self.paper_log = PaperLog(self.storage.db)
        # the same with the holder criteria (PROJE.md §4.6), side by side: own scores, bar and virtual trades
        self.paper_model_h = Model.load(paper.MODEL_H_PATH)
        self.paper_log_h = PaperLog(self.storage.db, "paper_log_h")
        self.book = Book(self.storage.db)
        self.live_log = LiveLog(self.storage.db)
        known, since = self.paper_log.known()
        self.follower = Follower(known, since, on_new=self.paper_log.remember, db=self.storage.db)
        # "2x oldu" for sent alerts: token -> [alert price, last buy was at 2x], up to LIVE_2X_DAYS (PROJE.md §0 D4)
        self.live_watch = {r["token"]: [r["p_alert"], False] for r in self.live_log.open(time.time()) if not r["sent_2x"]}
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
    def min_buy_usd(self) -> float:
        return float(self.storage.get_state("min_buy_usd", str(self.settings.fomo_min_buy_usd)))

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
        if self.paper_model:
            # one block timestamp per poll: spread the batch back over its blocks (~10 a second)
            top = max(t.block for t in trades)
            moments = []
            for t in sorted(trades, key=lambda x: x.block):
                ts = t.timestamp - (top - t.block) / paper.BLOCKS_PER_S
                trade = Trade(ts, t.block, int(t.side == "buy"), t.trader.lower(), t.usd or 0.0, t.amount or 0)
                self.watch_2x(t.token.lower(), trade)
                idx = self.follower.add(t.token, trade)
                if idx is not None:
                    moments.append((t.token, idx))
            for token, idx in moments:  # after the whole batch: same-block buys count, as in the research
                task = asyncio.create_task(self.score_moment(token, idx))
                self.tasks.append(task)
                task.add_done_callback(lambda done: self.tasks.remove(done) if done in self.tasks else None)
        for token in {t.token for t in trades if t.side == "buy"}:
            stats = self.tracker.stats(token, self.fomo_window)
            rising = stats["buyers"] >= self.min_buyers and stats["buy_usd"] >= self.min_buy_usd
            # the old trending alert (PROJE.md §0 D6): no analysis while its alerts are off (/durdur), it would only
            # compete with the paper test for the RPC
            if rising and self.alerts_on and self.storage.mark_alerted(token):
                if warmup:
                    # Already trending when the bot started: visible in /trend, no alert flood.
                    log.info("%s was already trending at startup; not alerting", token)
                    continue
                log.info("%s is rising on Fomo: %s", token, stats)
                await self.queue.put(Job(token, from_fomo=True))

    # --- paper test ---
    @property
    def live_on(self) -> bool:
        return self.storage.get_state("live_alerts", "0") == "1"

    @property
    def paper_notify(self) -> bool:
        return self.storage.get_state("paper_notify", "0") == "1"

    async def score_moment(self, token: str, idx: int):
        """A new coin's 5th distinct Fomo buyer: research features, model score, maybe a virtual trade."""
        try:
            key = token.lower()
            coin = self.follower.coins[key]
            trades = coin.trades
            t = trades[idx].ts
            supply = await self.rpc.try_call_fn(token, "totalSupply()", ["uint256"])
            index = self.analyzer.launches
            row = index.db.execute("SELECT block, curve, launcher FROM pons_launches WHERE token = ?",
                                   (key,)).fetchone() if index else None
            launch_ts = t - (trades[idx].block - row[0]) / paper.BLOCKS_PER_S if row else None
            first3 = coin.buyers[:3]
            features = paper.alert_features(trades, idx, paper.CHECKPOINT_BUYERS,
                                            float(supply[0]) if supply else None, launch_ts, self.book.rate(first3))
            if features is None:
                return
            p_now = next(x.price for x in reversed(trades) if x.side == 1 and x.price and x.ts <= t)
            self.book.watch(key, t, p_now, first3)
            now = time.time()
            score = self.paper_model.score(features)
            bar = self.paper_log.bar(self.paper_model, now)
            alert = score >= bar
            size = paper.size_for(self.paper_log.percentile(score, now)) if alert else None
            self.paper_log.add(key, t, score, bar, alert, size, features, now, features.get("depth_usd"))
            if alert:
                self.follower.keep(key, t + paper.MAX_HOLD + 3600)
                log.info("paper alert %s (score %.3f, bar %.3f, %.0f s after the 5th buyer)", token, score, bar, now - t)
                if self.live_on:
                    await self.send_live(token, t, trades[idx].block, p_now, features, row is not None, coin.buyers)
                elif self.paper_notify:
                    await self.broadcast(format_paper_alert(await self.symbol(token), token, features.get("fdv"), score, size,
                                                            now - t))
            if self.paper_model_h:
                await self.score_holder(key, coin, idx, float(supply[0]) if supply else None, row, features)
        except Exception:
            log.exception("paper scoring failed for %s", token)

    async def score_holder(self, key: str, coin, idx: int, supply_raw: float | None, launch: tuple | None,
                           features: dict):
        """The second paper model: the main criteria plus the holder ones from the coin's Transfer logs."""
        trades = coin.trades
        t, block, first = trades[idx].ts, trades[idx].block, trades[0]
        holder = dict.fromkeys(paper.HOLDER_FEATURES, math.nan)
        if t <= first.ts + paper.HOLDER_WINDOW:
            try:
                logs = await self.rpc.get_logs(paper.holder_window(first.block, launch[0] if launch else None), block,
                                               [paper.TRANSFER_TOPIC], address=key)
            except Exception as exc:  # not scored rather than scored without its holders
                log.warning("holder logs unavailable for %s: %s", key, exc)
                return
            holder = paper.holder_features(paper.parse_transfers(logs), key, block, t, first.block, first.ts, launch,
                                           supply_raw)
        both = {**features, **holder}
        now = time.time()
        score = self.paper_model_h.score(both)
        bar = self.paper_log_h.bar(self.paper_model_h, now)
        alert = score >= bar
        size = paper.size_for(self.paper_log_h.percentile(score, now)) if alert else None
        self.paper_log_h.add(key, t, score, bar, alert, size, both, now, features.get("depth_usd"))
        if alert:
            self.follower.keep(key, t + paper.MAX_HOLD + 3600)
            log.info("paper (holder) alert %s (score %.3f, bar %.3f)", key, score, bar)

    async def send(self, text: str, reply_to: dict | None = None) -> dict:
        """Sends to every chat; returns chat id -> message id (for replies)."""
        sent = {}
        for chat_id in self.settings.telegram_chat_ids:
            try:
                msg = await self.app.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML,
                                                      disable_web_page_preview=True,
                                                      reply_to_message_id=(reply_to or {}).get(str(chat_id)))
                sent[str(chat_id)] = msg.message_id
            except Exception:
                log.exception("could not send to %s", chat_id)
        return sent

    async def send_live(self, token: str, t: float, block: int, price: float, features: dict, pons: bool,
                        buyers: list[str]):
        """A real alert: elimination (unsellable), the fast message, then the safety report as a reply."""
        pm = self.settings.v4_pool_manager
        try:
            status, detail, pool = await asyncio.wait_for(live.sell_gate(self.rpc, pm, token, pons, buyers), 20)
        except Exception as exc:
            status, detail, pool = "bilinmiyor", f"kontrol tamamlanamadı ({type(exc).__name__})", None
        if status in ("honeypot", "vergi"):
            log.info("live: %s dropped (%s)", token, detail)
            return
        symbol = await self.symbol(token)
        msgs = await self.send(format_live_alert(symbol, token, features.get("fdv"), self.paper_model.top_hit_rate,
                                                 live.reasons(self.paper_model, features), (status, detail),
                                                 time.time() - t))
        self.live_log.add(token.lower(), t, price, block, pool, msgs, status)
        self.live_watch[token.lower()] = [price, False]
        try:
            report = await self.analyzer.analyze(token, None, self.fomo_stats(token))
            sellers = self.tracker.stats(token, 3600)["sellers"]
            trust = live.trust_score(live.trust_flags(report, sellers, pons, features.get("depth_usd")))
            await self.send(format_trust_reply(format_report(report, self.settings.blockscout_url), trust), msgs)
        except Exception:
            log.exception("live safety report failed for %s", token)

    def watch_2x(self, token: str, trade: Trade):
        """Two buys in a row at >= 2x a sent alert's price: "2x oldu" (no trade history needed, survives restarts)."""
        w = self.live_watch.get(token)
        if w is None or trade.side != 1 or not trade.price:
            return
        hit = trade.price >= 2 * w[0]
        if hit and w[1]:
            del self.live_watch[token]
            self.live_log.mark(token, sent_2x=1)
            task = asyncio.create_task(self.send_2x(token, trade.ts))
            self.tasks.append(task)
            task.add_done_callback(lambda done: self.tasks.remove(done) if done in self.tasks else None)
        else:
            w[1] = hit

    async def send_2x(self, token: str, ts: float):
        row = self.live_log.get(token)
        if row:
            await self.send(format_2x(await self.symbol(token), token, (ts - row["ts"]) / 60), json.loads(row["msg"] or "{}"))

    async def live_step(self, now: float):
        """Follow-ups of sent alerts: '2x oldu' once, and a warning when liquidity leaves the coin's V4 pool."""
        rows = self.live_log.open(now)
        head = await self.rpc.block_number() if any(r["pool"] and not r["warned"] for r in rows) else None
        pm = self.settings.v4_pool_manager
        for r in rows:
            token, reply = r["token"], json.loads(r["msg"] or "{}")
            if r["pool"] and not r["warned"] and head:
                if now - r["ts"] > live.LIQ_WATCH:
                    self.live_log.mark(token, warned=1)  # watched long enough
                    continue
                n = await live.liquidity_removed(self.rpc, pm, r["pool"], r["checked_block"] + 1, head)
                self.live_log.mark(token, checked_block=head)
                if n:
                    await self.send(format_liquidity_warning(await self.symbol(token), token, n), reply)
                    self.live_log.mark(token, warned=1)

    async def live_loop(self):
        while True:
            try:
                await self.live_step(time.time())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("live step failed")
            await asyncio.sleep(60)

    def paper_step(self, now: float):
        """Settles the first buyers' book, moves the open virtual trades on, forgets coins no longer needed."""
        self.book.settle(self.follower, now)
        for plog in (self.paper_log, self.paper_log_h):
            for token, ts, depth in plog.open_alerts():
                coin = self.follower.coins.get(token)
                if coin is None:  # restarted meanwhile: its trades are gone
                    plog.update(token, None, None, True, now)
                    continue
                trade = paper.paper_trade(coin.trades, ts, now)
                if trade is None:
                    continue
                depth = depth if depth and depth == depth else 3000.0  # unknown depth: a cautious pool
                expired = now - ts > paper.MAX_HOLD
                if trade["open"] == 0 or expired:
                    value = paper.last_value(coin.trades, now, trade["p_alert"]) if trade["open"] else None
                    ret = paper.net_return(trade, depth, 20.0, value)
                    plog.update(token, trade, ret, True, now)
                else:
                    value = paper.last_value(coin.trades, now, trade["p_alert"])
                    plog.update(token, trade, paper.net_return(trade, depth, 20.0, value), False, now)
        self.follower.prune(now)

    async def paper_loop(self):
        while True:
            try:
                self.paper_step(time.time())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("paper step failed")
            await asyncio.sleep(60)

    # --- analysis ---
    def fomo_stats(self, token: str) -> dict | None:
        stats = self.tracker.stats(token, self.fomo_window)
        if not (stats["buys"] or stats["sells"]):
            return None
        return {**stats, "churn_share_30m": fomo_churn(self.tracker, token)}

    async def worker(self):
        while True:
            job = await self.queue.get()
            try:
                report = await self.analyzer.analyze(job.token, None, self.fomo_stats(job.token))
                self.storage.save_report(job.token, report["score"], report)
                if self.alerts_on and report["score"] >= self.min_score:
                    await self.broadcast(format_report(report, self.settings.blockscout_url,
                                                       "🔥 Fomo'da yükselen token"))
            except Exception:
                log.exception("analysis failed for %s", job.token)
            finally:
                self.queue.task_done()

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

    async def cmd_karne(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        if not self.paper_model:
            await update.message.reply_text("Kâğıt test kapalı: model dosyası (rhscanner/paper_model.json) yok.")
            return
        arg = context.args[0] if context.args else ""
        hours = float(arg) if arg.replace(".", "", 1).isdigit() else None
        since = time.time() - hours * 3600 if hours else 0.0
        rows = self.paper_log.alerts(since)
        recent = [(await self.symbol(r["token"]), r) for r in rows[-8:]]
        other = None
        if self.paper_model_h:
            other = paper.summary(self.paper_log_h.alerts(since), self.paper_log_h.scored(since))
        await update.message.reply_html(format_paper(hours, paper.summary(rows, self.paper_log.scored(since)), recent,
                                                     self.paper_model.trained_until, other))

    async def cmd_live(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        arg = (context.args[0] if context.args else "").lower()
        if arg not in ("ac", "aç", "kapat"):
            await update.message.reply_text(f"Kullanım: /canli ac|kapat (şu an: {'açık' if self.live_on else 'kapalı'})")
            return
        self.storage.set_state("live_alerts", "0" if arg == "kapat" else "1")
        await update.message.reply_text("✅ Gerçek bildirimler " + ("kapandı." if arg == "kapat" else
                                        "açıldı: kâğıt testin seçtiği coinler satılabilirlik kontrolünden sonra gelecek."))

    async def cmd_paper_notify(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        arg = (context.args[0] if context.args else "").lower()
        if arg not in ("ac", "aç", "kapat"):
            await update.message.reply_text(f"Kullanım: /kagitbildirim ac|kapat (şu an: {'açık' if self.paper_notify else 'kapalı'})")
            return
        self.storage.set_state("paper_notify", "0" if arg == "kapat" else "1")
        await update.message.reply_text("✅ Kâğıt test mesajları " + ("kapandı." if arg == "kapat" else "açıldı."))

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        await update.message.reply_text(
            f"Fomo son blok: {self.storage.get_state('fomo_last_block', '-')}\n"
            f"RPC: {self.rpc.url.split('//')[-1]}\n"
            f"Fomo'da izlenen coin (son 1 saat): {len(self.tracker.trades)}\n"
            f"Analiz kuyruğu: {self.queue.qsize()}\n"
            f"Pons lansman indeksi: {self.analyzer.launches.count():,} coin\n"
            f"Bildirimler: {'açık' if self.alerts_on else 'kapalı'} · Min. skor: {self.min_score} · "
            f"Min. alıcı: {self.min_buyers} · Min. hacim: ${self.min_buy_usd:,.0f} / {self.settings.fomo_window_min:g} dk\n"
            f"Kâğıt test: {'açık' if self.paper_model else 'kapalı (model yok)'}"
            f"{' (ilk 24 saat: eski coinleri öğreniyor)' if self.follower.known_since and time.time() - self.follower.known_since < 86400 else ''}"
            f" · izlenen yeni coin {sum(c.eligible for c in self.follower.coins.values())} · son 24 saatte puanlanan "
            f"{self.paper_log.scored(time.time() - 86400)} · seçilen {len(self.paper_log.alerts(time.time() - 86400))}"
            f"{' · holderlı model seçti ' + str(len(self.paper_log_h.alerts(time.time() - 86400))) if self.paper_model_h else ''}\n"
            f"Gerçek bildirim: {'açık' if self.live_on else 'kapalı'}"
        )

    # --- lifecycle ---
    async def _post_init(self, app: Application):
        saved = self.storage.get_state("fomo_last_block")
        if saved is not None:
            try:
                if await self.rpc.block_number() - int(saved) <= self.settings.fomo_lookback_blocks:
                    self.follower.warmup_blocks = 0  # resumes right after its last block: no new coin was missed
            except Exception as exc:
                log.warning("head unknown at start (%s); new coins of the first minutes are skipped", exc)
        if self.settings.enable_fomo_watcher:
            watcher = FomoWatcher(self.rpc, self.settings, self.storage, self.tracker)
            self.tasks.append(asyncio.create_task(watcher.run(self.on_fomo_trades)))
            self.tasks.append(asyncio.create_task(REGISTRY.run(self.rpc, self.settings.v4_pool_manager)))
        self.tasks.append(asyncio.create_task(self.launch_loop()))
        if self.paper_model:
            self.tasks.append(asyncio.create_task(self.paper_loop()))
            self.tasks.append(asyncio.create_task(self.live_loop()))
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
        self.app.add_handler(CommandHandler("minhacim", self.cmd_min_usd))
        self.app.add_handler(CommandHandler("durdur", self.cmd_pause))
        self.app.add_handler(CommandHandler("devam", self.cmd_resume))
        self.app.add_handler(CommandHandler("durum", self.cmd_status))
        self.app.add_handler(CommandHandler("karne", self.cmd_karne))
        self.app.add_handler(CommandHandler("kagitbildirim", self.cmd_paper_notify))
        self.app.add_handler(CommandHandler("canli", self.cmd_live))
        self.app.run_polling()
