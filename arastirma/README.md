# İşlenmiş araştırma dosyaları

Her oturumda yeniden üretmemek için (PROJE.md §7). Klasör adı = üretildiği gün; veri o günün sabahına kadar.

`2026-10-12/`
- `winners.parquet` — `scripts/winner_study.py` çıktısı (Fomo 3./5./10./20. alıcı anları + kriterler + sonraki zirve), 3 Eylül – 12 Ekim
- `picks_top5.parquet` — `scripts/profit_study.py <db> winners.parquet 2026-09-10 5` "2x" modelinin gün gün (walk-forward) en iyi %5'i (10 Eylül – 11 Ekim, 668 seçim)
- `events_5x.jsonl.gz` — bu seçimlerden 3 saatte 5x yapan 153'ünün zincir olayları (curve + V4 işlemleri, likidite çekilmesi), bildirimden 5x'ten 70 dk sonrasına (`scripts/after5x.py --fetch`)
- `picks_top10.parquet` — aynı walk-forward'un en iyi %10'u (seçim payı sorusu, `scripts/share5x.py`)
- `events_3h.jsonl.gz` — en iyi %10'dan 5x yapmayanların zincir olayları, bildirimden 3 saat sonrasına (24 saatlikler dahil); **yarım** (12 Ekim'de 956 coinin ~290'ı indi). Devam: `share5x.py <db> picks_top10.parquet <açılmış events_3h.jsonl> --fetch` kaldığı yerden sürer

`2026-11-10/` (standart sınav, PROJE.md §4.16; veri 3 Eylül – 10 Kasım 15:03)
- `winners.parquet` — `winner_study.py` çıktısı (5. alıcı anları vb.), 3 Eylül – 10 Kasım
- `picks_top5.parquet` — `profit_study.py <db> winners.parquet 2026-09-10 5` "2x" modelinin walk-forward en iyi %5'i (802 seçim, 10 Eylül – 10 Kasım)
- `events_top5.jsonl.gz` — bu 802 seçimin zincir olayları, bildirimden 3 sa 15 dk sonrasına (`scorecard.py --fetch`); `scorecard.py` .gz'yi doğrudan okur
