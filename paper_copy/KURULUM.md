# Kâğıt Üstünde Kopyalama — Kurulum

Bu servis takip listesindeki Solana cüzdanlarını dinler ve onlar alım yaptığında
**sanal** pozisyon açar (1 sn, 3 sn ve 30 sn gecikmeyle), onlar satınca sanal olarak çıkar.
**Gerçek işlem yapmaz; cüzdan, özel anahtar veya para kullanmaz.**
Sonuçlar Telegram'a gelir, her akşam 21:00'de günlük rapor gönderilir.

## 1. Dosyaları VPS'e kopyala
```bash
sudo mkdir -p /opt/paper_copy
# bu klasördeki dosyaları /opt/paper_copy içine kopyala (scp, sftp vb.)
cd /opt/paper_copy
```

## 2. Python ortamını kur
```bash
sudo apt-get install -y python3-venv   # yoksa
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## 3. Ayarları gir
```bash
cp .env.example .env
nano .env     # HELIUS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```
Telegram için mevcut botunun token'ını ve sohbet ID'sini kullanabilirsin. Bu servis
sadece mesaj **gönderir**, komut dinlemez; mevcut botunla çakışmaz.

## 4. Dene
```bash
venv/bin/python paper_copy.py test-tg   # Telegram'a deneme mesajı gelmeli
venv/bin/python paper_copy.py           # çalıştır, Ctrl+C ile durdur
```

## 5. Sürekli çalışsın (systemd)
```bash
sudo cp paper-copy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paper-copy
journalctl -u paper-copy -f      # canlı log
```

## Kullanım
- Ara rapor: `venv/bin/python paper_copy.py rapor`
- Takip listesini değiştirmek: `wallets.txt` dosyasını düzenle, `sudo systemctl restart paper-copy`
- Sonuçlar `paper.db` (SQLite) dosyasında birikir.

## Ne zaman karar verilir?
2–3 hafta çalıştır. Günlük raporda **+1sn** satırında (anlık bir botun ulaşabileceği gecikme) kazanan oranı ve toplam SOL
sürekli pozitif değilse, bu cüzdanları gerçek parayla kopyalamak mantıklı değildir.
Pozitif olsa bile önce çok küçük tutarlarla dene; gerçek kayma burada varsayılan %1,5'ten büyük olabilir.

## Kredi kullanımı
Helius ücretsiz planı ayda 1 milyon kredi. Bu servis cüzdanları websocket ile dinlediği için
düşük tüketir; ağırlık yedek taramada (15 dakikada bir). Helius panelinden haftada bir kontrol et.
