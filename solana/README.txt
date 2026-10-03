Fomo'nun Solana işlemleri (pump.fun curve + PumpSwap), sunucudaki rhscanner/solana.py toplayıcısından.
Her gece rhscanner/solana_export.py ile gönderilir. Okumak için: scripts/solana_import.py.

<gün>/trades_<ss>.csv.gz  UTC ss:00'dan 6 saatlik işlemler: slot, ts, sig, venue (1 curve, 2 pumpswap), mint,
                          side (1 alım, 0 satış), user, lamports (SOL*1e9), tokens (ham, 6 ondalık), vsol, vtok
                          (curve sanal rezervleri), pool (pumpswap havuzu)
<gün>/stats.csv.gz        dakikalık Fomo işlem sayıları: minute, total, curve, pumpswap, other
<gün>/sol_price.csv.gz    5 dakikada bir SOL/USD: ts, usd
pools.csv.gz              PumpSwap havuzları: pool, base (coin), quote
