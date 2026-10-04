Fomo'nun BNB Chain işlemleri ve flap.sh lansmanları, sunucudaki rhscanner/bnb.py toplayıcısından.
Her gece rhscanner/solana_export.py --chain bnb ile gönderilir. Okumak için: scripts/solana_import.py --chain bnb.

<gün>/fomo_<ss>.csv.gz    UTC ss:00'dan 6 saatlik Fomo olay ayakları: block, ts, tx, li, emitter (entry / executor),
                          src, dst, token, amount (ham birim); alım = executor -> kullanıcı, coin ayağı
<gün>/usdc_in.csv.gz      executor'a giden USDC transferleri (satış tutarı; USDC 18 ondalık): block, ts, tx, li, src,
                          amount
<gün>/launches.csv.gz     flap.sh TokenCreated: token, block, ts, creator, name, symbol
