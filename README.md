# Fomo işlem arşivi (veri dalı)

Robinhood Chain'de Fomo üzerinden yapılan tüm alım-satımlar, gün başına bir parquet dosyası (UTC).
Kolonlar: block, ts (unix sn), token, side (1 alım / 0 satış), trader, usd (USDG; satışlarda tx'teki
USDG'den, ~%5 toplu tx'te yanlış olabilir), amount (ham token birimi). `supply.parquet`: coin arzları (ham).

Üretim: ana daldaki `scripts/fomo_download.py` + `scripts/data_export.py`.
Kullanım: `git fetch origin veri && git worktree add /tmp/veri origin/veri` →
`python scripts/data_import.py /tmp/veri trades.db`.
