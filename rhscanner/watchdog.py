"""Alarm when the bot goes blind (PROJE.md devir iş 5; DENETIM.md: the bot was blind for 15 days, 26 Oct - 10 Nov,
because Fomo moved to new contracts and nothing told us).

Two checks, every CHECK_S:
- silent: no Fomo trade seen for SILENT_S (the watcher is stuck, the RPC is down, or Fomo moved contracts).
- thin: the last THIN_WINDOW_S held < THIN_SHARE of the trades the same length held on average over the BASE_DAYS
  before it (the 26 Oct case: the old contracts still carried ~50 trades a day, so "no trade" alone fires late).
A warning is sent once when a check turns on, and a "düzeldi" once it turns off.
"""
from __future__ import annotations

SILENT_S = 30 * 60
THIN_WINDOW_S = 6 * 3600
THIN_SHARE = 0.1  # 20 Sep - 10 Nov (complete chain data): the lowest ratio was 0.24; the blind bot (26 Oct) ~0.003
BASE_DAYS = 7
MIN_BASE = 200  # a baseline under this many trades per window is too thin to judge
CHECK_S = 60


def thin_counts(db, now: float) -> tuple[int, float]:
    """(trades in the last THIN_WINDOW_S, the mean per THIN_WINDOW_S over the BASE_DAYS before) from fomo_log."""
    lo = now - THIN_WINDOW_S
    recent = db.execute("SELECT COUNT(*) FROM fomo_log WHERE ts >= ? AND ts <= ?", (lo, now)).fetchone()[0]
    base = db.execute("SELECT COUNT(*) FROM fomo_log WHERE ts >= ? AND ts < ?",
                      (lo - BASE_DAYS * 86400, lo)).fetchone()[0]
    return recent, base / (BASE_DAYS * 86400 / THIN_WINDOW_S)


def problems(now: float, last_trade: float, recent: int | None, base: float | None) -> set[str]:
    """The checks that are on now."""
    out = set()
    if now - last_trade >= SILENT_S:
        out.add("silent")
    if recent is not None and base is not None and base >= MIN_BASE and recent < THIN_SHARE * base:
        out.add("thin")
    return out


def message(kind: str, on: bool, now: float, last_trade: float, recent: int | None, base: float | None,
            last_block: str) -> str:
    """Telegram HTML (no bare '<')."""
    if kind == "silent":
        if on:
            return (f"⚠️ <b>Bot kör olabilir:</b> {int((now - last_trade) // 60)} dakikadır hiç Fomo işlemi görmedi "
                    f"(son işlenen blok {last_block}). RPC, bot ya da Fomo'nun kontrat değişikliği olabilir; "
                    f"<code>journalctl -u rhscanner -n 50 --no-pager</code> ile bak.")
        return f"✅ Fomo işlemleri yeniden geliyor (son işlenen blok {last_block})."
    if on:
        return (f"⚠️ <b>Fomo işlemleri birden düştü:</b> son {THIN_WINDOW_S // 3600} saatte {recent} işlem, önceki "
                f"{BASE_DAYS} günün ortalaması {base:,.0f}. Fomo yeni bir kontrata geçmiş olabilir (26 Ekim'deki gibi).")
    return f"✅ Fomo işlem sayısı normale döndü (son {THIN_WINDOW_S // 3600} saatte {recent})."


class Watchdog:
    def __init__(self, now: float):
        self.last_trade = now  # a fresh start gets SILENT_S of grace
        self.on: set[str] = set()
        self.counts: tuple[int | None, float | None] = (None, None)
        self.counted_at = now  # first count after 30 min: a restart first catches up on the blocks it missed

    def seen(self, now: float):
        self.last_trade = now

    def step(self, now: float, db, last_block: str) -> list[str]:
        """Messages to send now (state changes only)."""
        if db is not None and now - self.counted_at >= 30 * 60:
            self.counts, self.counted_at = thin_counts(db, now), now
        recent, base = self.counts
        now_on = problems(now, self.last_trade, recent, base)
        out = [message(k, k in now_on, now, self.last_trade, recent, base, last_block)
               for k in sorted(now_on ^ self.on)]
        self.on = now_on
        return out
