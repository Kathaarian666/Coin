Robinhood Chain'deki bütün Fomo işlemleri, sunucudaki botun canlı gördüğü haliyle (rhscanner.db fomo_log).
Her gece rhscanner/solana_export.py --chain robinhood ile gönderilir. Araştırma veritabanına eklemek için:
scripts/solana_import.py /tmp/veri fomo.db --chain robinhood (fomo_download.py biçimi; sadece son bloktan sonrası).

<gün>/trades.csv.gz       block, ts (blok zamanı, toplu sorgunun son bloğundan ~9,93 blok/sn ile geri), token, side
                          (1 alım, 0 satış), trader, usd (satışlarda USDG transferinden; okunamazsa boş), amount (ham)
