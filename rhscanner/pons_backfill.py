"""Replay the last few days of Pons curve trading into the outcome log.

The live watcher only measures coins born after it started; the chain keeps
every curve trade, so the same signals (pons.detect_signals, same tiers and
junk filter) can be found in the past and scored from the curve prices that
followed. Run it once on the server, next to the running bot:

  python -m rhscanner pons-backfill 3

Limits: ETH is priced at today's rate (ratios, which /karne reports, are
unaffected; the USD buying bar is slightly off); a coin that graduated has no
curve prices after that, so its samples stop at graduation (DexScreener's
pair creation time).
"""

import asyncio
import bisect
import logging
import time

from .launches import LaunchIndex
from .outcomes import CHECKPOINTS_MIN, OutcomeLog
from .pons import (BLOCKS_PER_MIN, DAY_BLOCKS_PONS, PonsTracker, detect_signals, eth_usd_price,
                   fetch_curve_logs, parse_curve_logs, pons_tiers)

log = logging.getLogger(__name__)

STEP_BLOCKS = 5000  # ~2.5k curve trades per query at current rates (the node caps a query at 10k logs)
BATCH_BLOCKS = 100  # signals are checked every ~10 s of chain time, like the live watcher
ATTEMPTS = 20
PAUSE_SEC = 30.0  # the public RPC rate-limits hard, and the bot shares it


async def _patiently(call, *args):
    """A node call retried with long pauses: one refused query must not lose a long replay."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await call(*args)
        except Exception as exc:
            if attempt == ATTEMPTS:
                raise
            log.warning("RPC hatası (%s), %.0f sn sonra tekrar denenecek (%d/%d)", exc, PAUSE_SEC, attempt, ATTEMPTS)
            await asyncio.sleep(PAUSE_SEC)


def _existing(db) -> set[tuple[str, str]]:
    return {(token, kind.removesuffix("_junk"))
            for token, kind in db.execute("SELECT token, kind FROM signals WHERE kind LIKE 'pons%'")}


def price_samples(history: list[tuple[float, float]], ts: float, now: float,
                  graduated_at: float | None) -> dict[int, float | None]:
    """Curve price at each checkpoint that has passed: the last trade at or before it."""
    times = [t for t, _ in history]
    samples = {}
    for minute in CHECKPOINTS_MIN:
        at = ts + minute * 60
        if at > now:
            break
        if graduated_at is not None and at >= graduated_at:
            break  # off the curve: its price is on the DEX now
        i = bisect.bisect_right(times, at) - 1
        samples[minute] = history[i][1] if i >= 0 else None
    return samples


async def backfill(settings, rpc, storage, dexscreener, days: float) -> dict:
    index = LaunchIndex(storage.db)
    outcomes = OutcomeLog(storage.db)
    eth_usd = await eth_usd_price(dexscreener, settings.weth)
    if not eth_usd:
        raise SystemExit("ETH fiyatı alınamadı (DexScreener)")
    head = await rpc.block_number()
    lo = head - int(days * DAY_BLOCKS_PONS)
    max_age_blocks = int(settings.pons_max_age_min * BLOCKS_PER_MIN)
    log.info("Pons lansmanlarının curve adresleri dolduruluyor...")
    filled = await _patiently(index.fill_curves, rpc, lo - max_age_blocks, head)
    log.info("%d lansmana curve eklendi", filled)

    tracker = PonsTracker(max_age=settings.pons_max_age_min * 60)
    tiers = pons_tiers(settings)
    seen = _existing(storage.db)
    window = settings.fomo_window_min * 60
    found: list[tuple[str, str, float, dict, str]] = []  # token, kind, ts, features, curve
    history: dict[str, list[tuple[float, float]]] = {}  # curve -> (ts, ETH price) from its first signal on

    t_prev = await _patiently(rpc.block_timestamp, lo - 1)
    steps = (head - lo) // STEP_BLOCKS + 1
    for step, start in enumerate(range(lo, head + 1, STEP_BLOCKS), 1):
        end = min(head, start + STEP_BLOCKS - 1)
        trades = parse_curve_logs(await _patiently(fetch_curve_logs, rpc, start, end))
        t_end = await _patiently(rpc.block_timestamp, end)
        span = max(1, end - start + 1)
        for trade in trades:  # block times, interpolated inside the window
            trade.timestamp = t_prev + (trade.block - start + 1) / span * (t_end - t_prev)
        trades.sort(key=lambda t: t.block)
        i = 0
        for batch_end in range(start + BATCH_BLOCKS - 1, end + BATCH_BLOCKS, BATCH_BLOCKS):
            batch = []
            while i < len(trades) and trades[i].block <= batch_end:
                batch.append(trades[i])
                i += 1
            if not batch:
                continue
            for trade in batch:
                tracker.add(trade)
                if trade.curve in history and trade.tokens > 0:
                    history[trade.curve].append((trade.timestamp, trade.eth / trade.tokens))
            now = batch[-1].timestamp
            for token, kind, features in detect_signals(tracker, index, batch, tiers, settings.pons_max_age_min,
                                                        window, eth_usd, seen, now):
                curve = index.curve_of(token)
                found.append((token, kind, now, features, curve))
                if curve not in history:
                    history[curve] = [(now, tracker.price(curve))]
        tracker.prune(t_end)
        t_prev = t_end
        if step % 20 == 0 or step == steps:
            log.info("Pons geçmişi: %d/%d adım, %d sinyal", step, steps, len(found))

    graduated: dict[str, float] = {}
    tokens = sorted({token for token, *_ in found})
    for k in range(0, len(tokens), 30):
        for pair in await dexscreener.tokens(tokens[k: k + 30]):
            token = (pair.get("baseToken") or {}).get("address", "").lower()
            created = (pair.get("pairCreatedAt") or 0) / 1000
            if token and created:
                graduated[token] = min(created, graduated.get(token, created))

    now = time.time()
    written = 0
    for token, kind, ts, features, curve in found:
        samples = {m: p * eth_usd if p else None
                   for m, p in price_samples(history[curve], ts, now, graduated.get(token)).items()}
        features = {**features, "backfill": True}
        if token in graduated:
            features["graduated_min"] = round((graduated[token] - ts) / 60, 1)
        written += outcomes.record_history(token, kind, ts, features, samples, now)
    kinds: dict[str, int] = {}
    for _, kind, *_ in found:
        kinds[kind] = kinds.get(kind, 0) + 1
    return {"signals": len(found), "written": written, "graduated": len(graduated), "by_kind": kinds}
