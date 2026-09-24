# Robinhood Chain Token Tarayıcı (Telegram Botu)

Robinhood Chain'de yeni açılan token havuzlarını 7/24 tarar, her token için güvenlik
kontrolleri yapar ve sonucu **0–100 arası bir güven skoruyla** Telegram'a gönderir.
Fomo'da görünen Robinhood Chain token'ları da bu havuzlardan gelir.

> ⚠️ Yatırım tavsiyesi değildir. Bot kötü token'ları elemeye yardımcı olur, ama hiçbir
> otomatik kontrol her dolandırıcılığı yakalayamaz. "Yükselir mi?" sorusunu cevaplamaz.

## Ne kontrol ediyor?

| Kontrol | Nasıl |
|---|---|
| **Honeypot** (alınır ama satılamaz) | Alım + satış, `eth_call` ile gerçek havuza karşı **simüle edilir** (para harcanmaz) |
| **Alım / satış vergisi** | Aynı simülasyonda gerçek vergi oranı ölçülür |
| **Sahiplik** | `owner()` devredilmiş (renounced) mi? |
| **Tehlikeli fonksiyonlar** | Kontrat kodunda mint, kara liste, vergi değiştirme, pause, limit fonksiyonları aranır |
| **Yükseltilebilir kontrat** | EIP-1967 proxy tespiti (kod sonradan değiştirilebilir mi?) |
| **Kaynak kodu doğrulanmış mı** | Blockscout |
| **Likidite** | Havuzdaki ETH miktarı |
| **LP yakılmış / kilitli mi** | LP token'larının ne kadarı yakılmış (rugpull riski) |
| **Cüzdan dağılımı** | İlk 10 cüzdan, en büyük cüzdan, geliştiricinin payı, yakılan arz |
| **Piyasa** | DexScreener: FDV, likidite ($), son 1 saat alım/satım, sosyal linkler |
| **V4 hook'ları** | Uniswap V4 havuzunda alım/satımı engelleyebilecek hook var mı? |

Yeni havuzlar Uniswap V2 / V3 / V4 olay imzalarıyla yakalanır. Böylece Uniswap'e
likidite ekleyen launchpad'ler de (mezun olan token'lar) kapsanır.

**Skor:** 🟢 75–100 düşük risk · 🟡 50–74 orta · 🔴 1–49 yüksek · ⛔ 0 tehlikeli (honeypot vb.)

## Kurulum

### 1. Telegram botu oluşturun
1. Telegram'da **@BotFather**'a `/newbot` yazın, bir isim verin.
2. Verdiği **token**'ı kimseyle paylaşmayın, sadece `.env` dosyasına yazacaksınız.

### 2. Sunucu (ücretsiz)
Bot 7/24 açık bir bilgisayarda çalışmalı. Önerilen: **Oracle Cloud Always Free**.
1. [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) üzerinden hesap açın (kart doğrulaması ister, ücret çekmez).
2. *Compute → Instances → Create* ile **Ubuntu** seçip bir "Always Free eligible" makine oluşturun.
3. SSH ile bağlanın.

Alternatif: evde şarjda duran eski bir Android telefon + **Termux** uygulaması (`pkg install python git`).

### 3. Botu kurun
```bash
git clone https://github.com/kathaarian666/coin.git Coin
cd Coin
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env        # TELEGRAM_BOT_TOKEN satırını doldurun
.venv/bin/python -m rhscanner
```
Botunuza Telegram'da `/start` yazın. Size **sohbet ID'nizi** söyleyecek. Bu ID'yi `.env`
içindeki `TELEGRAM_CHAT_IDS=` satırına yazın ve botu yeniden başlatın. Bot sadece bu ID'lere cevap verir.

### 4. Sürekli çalışması için (sunucuda)
```bash
sudo cp deploy/rhscanner.service /etc/systemd/system/
sudo systemctl enable --now rhscanner
journalctl -u rhscanner -f      # logları izlemek için
```
(Kullanıcı adınız veya klasörünüz farklıysa servis dosyasındaki yolları düzenleyin.)

## Telegram komutları

| Komut | Açıklama |
|---|---|
| `/check 0x...` | Herhangi bir token'ı hemen analiz et |
| `/minskor 60` | Skoru 60'ın altındaki yeni token'lar için bildirim gönderme |
| `/durdur` / `/devam` | Otomatik bildirimleri kapat / aç |
| `/durum` | Son taranan blok, görülen token sayısı, kuyruk |

Botu açmadan tek bir token'ı terminalden de kontrol edebilirsiniz:
```bash
.venv/bin/python -m rhscanner check 0xTOKEN_ADRESI
```

## Bilinen sınırlamalar

- **Honeypot simülasyonu şimdilik sadece Uniswap V2 tipi WETH havuzlarında** yapılıyor.
  V3/V4 havuzlarında "simüle edilemedi" uyarısı çıkar.
- Bazı anti-bot korumaları simülasyonu yanıltabilir ("alım başarısız" uyarısı).
- `owner()` sıfır görünse bile gizli yönetici rolleri olabilir. Kodu doğrulanmamış kontratlarda dikkatli olun.
- V3/V4 LP kilitleri henüz doğrulanamıyor.
- Public RPC hız sınırlıdır. Token yoğunluğu çok artarsa ücretsiz bir RPC sağlayıcısına
  (Alchemy/QuickNode vb.) geçip `RPC_URL`'i değiştirmek yeterli.

## Geliştirme

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
Testler yerel bir EVM (py-evm) üzerinde sahte WETH, Uniswap V2 havuzu ve vergili/honeypot
token'larla gerçek simülasyonu çalıştırır.

Honeypot kontratı (`contracts/HoneypotProbe.sol`) değişirse yeniden derleyin:
```bash
npm install --no-save solc@0.8.26
node scripts/compile_contracts.mjs
```

## Proje yapısı

```
rhscanner/
  discovery.py      yeni havuzları yakalar (V2/V3/V4 olayları)
  analyzer.py       tüm kontrolleri çalıştırıp raporu oluşturur
  checks/           contract, honeypot, liquidity, holders kontrolleri
  scoring.py        0–100 güven skoru
  report.py         Telegram mesaj formatı
  bot.py            Telegram botu + tarayıcı döngüsü
contracts/          honeypot simülasyon kontratı (+ test kontratları)
tests/              testler
```

## Yol haritası

- [x] Robinhood Chain tarayıcı + güvenlik kontrolleri + Telegram botu
- [ ] Sunucuya kurulum ve canlı ayar (eşikler, gerçek verilerle kalibrasyon)
- [ ] V3/V4 honeypot simülasyonu
- [ ] Geliştirici geçmişi (aynı cüzdanın önceki token'ları rug oldu mu?)
- [ ] Sniper / bundle tespiti, momentum takibi (token'ı 5–15 dk sonra yeniden kontrol)
- [ ] Solana (ayrı proje)
