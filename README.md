# Fomo · Robinhood Chain Token Tarayıcı (Telegram Botu)

**Fomo** uygulamasında Robinhood Chain'de alınıp satılan coinleri canlı izler. Bir coini kısa
sürede yeterince farklı Fomo kullanıcısı almaya başlayınca güvenlik kontrollerini yapar ve
sonucu **0–100 arası bir güven skoruyla** Telegram'a gönderir.

> ⚠️ Yatırım tavsiyesi değildir. Bot kötü token'ları elemeye yardımcı olur, ama hiçbir
> otomatik kontrol her dolandırıcılığı yakalayamaz. "Yükselir mi?" sorusunu cevaplamaz.

## Fomo'daki coinleri nasıl görüyor?

Fomo, EVM zincirlerinde işlemleri ERC-4337 akıllı cüzdanlarla yapıyor. Robinhood Chain'deki
her Fomo alım/satımı aynı iki kontrattan geçiyor ve her adımda bir olay (event) bırakıyor:

| Kontrat | Görevi |
|---|---|
| `0xccc88a9d1b4ed6b0eaba998850414b24f1c315be` | Giriş: kullanıcının ödediği (USDG/ETH ya da satılan coin) |
| `0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f` | Yürütücü: swap'ı yapıp coini/USDG'yi kullanıcıya teslim eder |

Bu olaylardan her coin için **kaç farklı Fomo kullanıcısının aldığı/sattığı ve dolar hacmi**
çıkarılır. Fomo hesabı, API anahtarı ya da ücretli servis gerekmez; hepsi herkese açık zincir
verisidir. (Bu kontratlar bir Fomo kullanıcısının alımları izlenerek bulundu; Fomo tarafından
resmî olarak duyurulmuş değildir. Fomo altyapısını değiştirirse `rhscanner/fomo.py` güncellenmeli.)

**Takip mesajı:** Her bildirimden `FOLLOWUP_MIN` (15) dakika sonra fiyat ve likidite değişimi, Fomo'da satış
yapılabildiği ve satış baskısı tekrar kontrol edilip kısa bir güncelleme gönderilir (likidite yarıdan fazla düşerse rug uyarısı).

**Bildirim kuralı:** `FOMO_WINDOW_MIN` (10) dakikada en az `FOMO_MIN_BUYERS` (10) farklı
alıcı → analiz → skor `MIN_SCORE_ALERT` (50) ve üstüyse Telegram bildirimi. Her coin bir kez
bildirilir. Bot açıldığında zaten trend olan coinler için toplu bildirim atılmaz (`/trend` ile görülür).

## Ne kontrol ediyor?

| Kontrol | Nasıl |
|---|---|
| **Fomo akışı** | Farklı alıcı/satıcı sayısı, alım/satım hacmi ($), satış baskısı |
| **Satılabilirlik** | Fomo'da farklı kullanıcılar başarıyla satabildiyse honeypot değildir |
| **Honeypot simülasyonu** | Uniswap V2 havuzlarında alım + satış `eth_call` ile simüle edilir (para harcanmaz) |
| **Alım / satım vergisi** | Aynı simülasyonda ölçülür |
| **Sahiplik** | `owner()` devredilmiş mi, sahibi bir kontrat mı? |
| **Tehlikeli fonksiyonlar** | Kodda mint, kara liste, vergi değiştirme, pause, limit fonksiyonları |
| **Yükseltilebilir kontrat** | EIP-1967 proxy tespiti |
| **Likidite** | DexScreener ($) ve havuzdaki ETH; en derin havuz seçilir (ETH, USDG ya da hisse token'ı paritesi) |
| **Uniswap V4 hook'u** | Hook'un son 3 günde kaç havuzda kullanıldığı (6 saatte bir yenilenir): yaygın launchpad hook'u mu, nadir mi, yükseltilebilir mi? |
| **Cüzdan dağılımı** | Transfer kayıtlarından RPC ile: ilk 10 cüzdan, en büyük cüzdan, kontratlardaki pay |
| **Piyasa** | DexScreener: FDV, son 1 saat alım/satım, sosyal linkler |

**İki ayrı skor:**
- 🛡️ **Güven skoru** (rug/tuzak riski): kontrat, likidite, holder dağılımı, satılabilirlik, lansman (dev/bundle/sniper).
- 🚀 **Momentum skoru** (vur-kaç için şu an gerçek alım hızlanıyor mu): son 5/10 dk Fomo alıcıları ve ivme,
  alım/satım oranı, alıcıların hâlâ tutma oranı, tek cüzdan ağırlığı, Fomo'nun toplam hacimdeki payı (organik akış),
  coinin yaşı, son 1 saat/5 dk fiyat hareketi, Telegram/X/web sitesi, likidite derinliği.
  Ağırlıklar ilk tahmindir; `/karne` sonuçlarıyla kalibre edilecek.

**Sonuç kaydı ve karne:** Bildirim giden, filtreye takılan ve karşılaştırma için "gölge" (eşiğin yarısını geçen,
analiz edilmemiş) coinlerin fiyat ve likiditesi 0, 5, 10 … 1440. dakikalarda DexScreener'dan kaydedilir.
`/karne [saat]` her grup ve momentum aralığı için 1 saatte 2x, 24 saatte 2x/5x, yarıya düşme ve rug oranlarını gösterir.

**Güven skoru:** 🟢 75–100 düşük risk · 🟡 50–74 orta · 🔴 1–49 yüksek · ⛔ 0 tehlikeli (honeypot vb.)

## Kurulum

### 1. Telegram botu oluşturun
1. Telegram'da **@BotFather**'a `/newbot` yazın, bir isim verin.
2. Verdiği **token**'ı kimseyle paylaşmayın, sadece `.env` dosyasına yazacaksınız.

### 2. Sunucu (ücretsiz)
Bot 7/24 açık bir sunucuda çalışmalı. Önerilen: **Oracle Cloud Always Free**, Ubuntu 24.04
(VM.Standard.A1.Flex kapasite hatası verirse VM.Standard.E2.1.Micro yeterli).
Sunucuya bağlanmak için bilgisayara bir şey kurmak gerekmez: Oracle konsolundaki
**Cloud Shell** (tarayıcı içi terminal) kullanılabilir.

### 3. Tek komutla kurulum
Sunucuya bağlandıktan sonra:
```bash
curl -fsSL https://raw.githubusercontent.com/Kathaarian666/Coin/refs/heads/claude/fomo-coin-scanner-app-mhz9rk/deploy/install.sh | bash
```
Betik paketleri kurar, kodu indirir, Telegram token'ını sorar, botu 7/24 çalışan bir servis
olarak başlatır, sonra botta `/start` yazınca gelen **sohbet ID'sini** sorar. Güncellemek için
aynı komut (veya `bash ~/Coin/deploy/install.sh`) tekrar çalıştırılır.

Loglar: `journalctl -u rhscanner -f` · Yeniden başlatma: `sudo systemctl restart rhscanner`

## Telegram komutları

| Komut | Açıklama |
|---|---|
| `/trend` | Şu an Fomo'da en çok alınan 10 coin (son 15 dk) |
| `/karne 24` | Son 24 saatteki sinyallerin sonuçları (bildirim / filtre / gölge, momentum aralıkları) |
| `/check 0x...` | Herhangi bir token'ı hemen analiz et |
| `/minskor 60` | Skoru 60'ın altındakiler için bildirim gönderme |
| `/minalici 15` | Bildirim için 10 dakikada gereken farklı Fomo alıcısı sayısı |
| `/durdur` / `/devam` | Otomatik bildirimleri kapat / aç |
| `/durum` | Son taranan blok, görülen token sayısı, kuyruk |

Botu açmadan terminalden de kullanabilirsiniz:
```bash
.venv/bin/python -m rhscanner trend        # son ~10 dk Fomo'da en çok alınanlar
.venv/bin/python -m rhscanner trend 3      # ... ve ilk 3'ünün tam analizi
.venv/bin/python -m rhscanner check 0xTOKEN_ADRESI
```

## Bilinen sınırlamalar

- **Honeypot simülasyonu sadece Uniswap V2 tipi WETH havuzlarında** yapılıyor. Fomo coinlerinin
  çoğu V4'te; onlarda satılabilirlik, Fomo kullanıcılarının gerçek satışlarından anlaşılıyor.
- Public Blockscout API'si sunuculardan gelen istekleri Cloudflare ile engelliyor. Bu yüzden
  "kaynak kodu doğrulanmış mı" bilgisi çoğu zaman alınamaz; holder verisi RPC'den hesaplanır.
- Bazı anti-bot korumaları simülasyonu yanıltabilir ("alım başarısız" uyarısı).
- Çok işlem gören coinlerde holder taraması 10–30 saniye sürebilir (public RPC sınırları).
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
  fomo.py           Fomo alım/satım akışını zincirden okur, coin bazında sayar
  discovery.py      yeni havuzları yakalar (V2/V3/V4 olayları, opsiyonel)
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
- [x] Fomo akışını zincirden okuma, Fomo'da yükselen coinler için bildirim
- [ ] Sunucuya kurulum ve canlı ayar (eşikler, gerçek verilerle kalibrasyon)
- [ ] Pons / FomoPad launchpad'lerinden coin doğduğu anda yakalama
- [ ] V3/V4 honeypot simülasyonu
- [ ] Geliştirici geçmişi (aynı cüzdanın önceki token'ları rug oldu mu?)
- [ ] Sniper / bundle tespiti, momentum takibi (token'ı 5–15 dk sonra yeniden kontrol)
- [ ] Solana (ayrı proje)
