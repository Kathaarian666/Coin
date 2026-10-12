# İşlenmiş araştırma dosyaları

Her oturumda yeniden üretmemek için (PROJE.md §7). Klasör adı = üretildiği gün; veri o günün sabahına kadar.

`2026-10-12/`
- `winners.parquet` — `scripts/winner_study.py` çıktısı (Fomo 3./5./10./20. alıcı anları + kriterler + sonraki zirve), 3 Eylül – 12 Ekim
- `picks_top5.parquet` — `scripts/profit_study.py <db> winners.parquet 2026-09-10 5` "2x" modelinin gün gün (walk-forward) en iyi %5'i (10 Eylül – 11 Ekim, 668 seçim)
- `events_5x.jsonl.gz` — bu seçimlerden 3 saatte 5x yapan 153'ünün zincir olayları (curve + V4 işlemleri, likidite çekilmesi), bildirimden 5x'ten 70 dk sonrasına (`scripts/after5x.py --fetch`)
