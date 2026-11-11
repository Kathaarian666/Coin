Fomo'nun BNB Chain işlemleri ve flap.sh lansmanları, sunucudaki rhscanner/bnb.py toplayıcısından.
Her gece rhscanner/solana_export.py --chain bnb ile gönderilir. Okumak için: scripts/solana_import.py --chain bnb.

<gün>/fomo_<ss>.csv.gz    UTC ss:00'dan 6 saatlik Fomo olay ayakları: block, ts, tx, li, emitter (entry / executor),
                          src, dst, token, amount (ham birim); alım = executor -> kullanıcı, coin ayağı
<gün>/usdc_in.csv.gz      executor'a giden USDC transferleri (satış tutarı; USDC 18 ondalık): block, ts, tx, li, src,
                          amount
<gün>/launches.csv.gz     flap.sh TokenCreated: token, block, ts, creator, name, symbol
<gün>/watch.csv.gz        5. Fomo alıcısından 3 sa 15 dk izlenen coinler (11 Kasım'dan): token, block, ts, until_ts
<gün>/coin_xfer.csv.gz    izlenen coinlerin bütün Transfer'leri: block, ts, tx, li, token, src, dst, amount
<gün>/venue_logs.csv.gz   o işlemlerin ham logları (havuz olayları; coin başına ~15 sn'de bir işlem): block, ts, tx, li,
                          address, topics (virgülle), data — havuz derinliği ve çıkış araştırmada çözülür (PROJE.md §4.17)
