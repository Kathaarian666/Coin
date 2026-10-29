Robinhood Chain'deki bütün Fomo işlemleri, sunucudaki botun canlı gördüğü haliyle (rhscanner.db fomo_log).
Her gece rhscanner/solana_export.py --chain robinhood ile gönderilir. Araştırma veritabanına eklemek için:
scripts/solana_import.py /tmp/veri fomo.db --chain robinhood (fomo_download.py biçimi; sadece son bloktan sonrası).

<gün>/trades.csv.gz       block, ts (blok zamanı, toplu sorgunun son bloğundan ~9,93 blok/sn ile geri), token, side
                          (1 alım, 0 satış), trader, usd (satışlarda USDG transferinden; okunamazsa boş), amount (ham)

29 Ekim: 2026-10-22 … 2026-10-28 zincirden yeniden yazıldı (scripts/fomo_download.py, iki Fomo kontrat çifti): Fomo 26 Ekim ~14:00 UTC'de
yeni kontratlara geçti, bot o günleri eksik görmüştü (PROJE.md §0 B7). 2026-10-29 ve düzeltme sunucuya kurulana kadarki saatler hâlâ eksik.
