# Fomo Coin Tarayıcı — Proje Belgesi

Son güncelleme: 2 Ekim (çıkış stratejisi ızgarası). Bu belge projenin tek özetidir: ne yapmak istiyoruz, nerede duruyoruz, neyi kanıtladık,
neyi denedik ve bıraktık, sırada ne var. Ayrıntılı tarihçe ve silinen eski betikler (`rise_model`, `copy_study`, `ride_test`, `winner_report`) git geçmişinde.

## 1. Amaç

Fomo uygulamasında (Robinhood Chain) işlem gören **yeni çıkmış coinlerde**:

1. **Güvenli olanları** ayırmak: satılabilir, tuzak değil.
2. **Ciddi yükselecek olanları** (2x, 5x, 10x, 100x; süresi önemli değil) **mümkün olduğunca erken** tespit etmek.
3. Sonra bunu kârlı bir al-sat kuralına çevirmek. Önce sabit $100 test tutarıyla; pozisyon büyüklüğü, risk yönetimi
   ve gerçek işlem en son.

Kullanıcı kararları:
- Sadece ücretsiz kaynaklar. X/Twitter API pahalı, şimdilik yok.
- Fomo içindeki "thesis" yazıları kullanılmaz.
- Karar sadece zincir verisiyle verilir. DexScreener örnekleri yanıltıcıydı.

## 2. Şu anki durum

**Bot (`rhscanner/`, sunucuda systemd servisi):** 1 Ekim'de sadeleştirildi. Fomo işlemlerini izliyor. Bir coin 10 dakikada
yeterli alıcıya (`/minalici`) ve hacme (`/minhacim`) ulaşınca güven taraması yapıyor. Skor `/minskor` eşiğinin
üstündeyse Telegram'a rapor gönderiyor.
- Güven taraması: satılabilirlik, honeypot simülasyonu, kontrat, likidite, V4 hook, holder, geliştirici geçmişi,
  sniper/bundle, sahte hacim.
- Komutlar: `/check` `/trend` `/minskor` `/minalici` `/minhacim` `/durdur` `/devam` `/durum`.
- Silinenler (git geçmişinde): momentum, rug riski, ÇIK/DİKKAT, erken sinyal, DexScreener tabanlı bütün ölçüm komutları.
- **Açık nokta:** sadeleştirilmiş sürüm sunucuya kuruldu mu, bildirimler kapalı mı (`/durdur`), kullanıcıyla teyit edilmeli.

**Araştırma:** Örnek dışı pozitif bir strateji bulundu: tarama + 1 saat tut (bölüm 3.3). Kârı az sayıda büyük işlem getiriyor. Henüz bota eklenmedi.

## 3. Kanıtlanmış bulgular (zincir verisi, 17–28 Eylül)

### 3.1 Piyasanın gerçekleri
- Günde ~2.000 yeni coin Fomo'da görünüyor, Pons'ta günde ~6.500 lansman var. Fomo coinlerinin %86'sı hiç 10 alıcıya
  ulaşmıyor.
- **Fomo, coinin küçük bir parçası.** Fomo'da 3. alıcı geldiğinde coinin zincirde zaten ~40+ holder'ı var. Holder'ların
  sadece %9-20'si Fomo kullanıcısı.
- Ciddi yükselişler var: ilk Fomo fiyatından **günde ~44 coin 10x+** yapıyor (zirve medyanı 19x, zirveye ~4 saat).
  Ama aynı anda benzer görünen yüzlerce coin ölüyor. 72 saat sonra medyan fiyat ilk fiyatın ~%30'u.
- 2x yapanlar önce neredeyse düşmüyor (dip medyanı 0,98x). 2x'lerin 2/3'ü ilk 30 dakikada geliyor.
- Maliyet: $100'lık al-sat 1x'te bile ~$5 ($5,6k havuz) ile $19 ($1k havuz) arası. Fomo komisyonu yön başına en az
  $0,95; kayma havuz derinliğine bağlı.

### 3.2 Yükselecek coini ne ayırıyor? (Fomo'da 3. alıcı anı)
İnternet araştırması (Pump.fun akademik çalışmaları, GMGN/Axiom kontrol listeleri) ve bizim veri aynı şeyi söylüyor.
Kazananlar o anda şöyle görünüyor:
- **Hızlı, büyük, dağınık alım:** işlem başına daha fazla $, k. alıcıya daha hızlı ulaşma, en büyük alıcının payı düşük.
- **Henüz satan yok.**
- **Küçük FDV** (~$14k'ya karşı ~$18k), lansmana yakın.
- Holder tarafında: ilk 10 cüzdanın payı, transfer yoğunluğu, sniper payı. Küçük katkı yapıyorlar.
- **Ayırmayanlar:** geliştiricinin geçmişi, yeni cüzdan oranı, genel piyasa hareketi, cüzdan kopyalama (başarı kalıcı
  değil).

Seçicilik 2-3 kat. Fomo 3. alıcısında, taramanın en iyi %10'u:

| | ≥2x | ≥5x | ≥10x |
|---|---|---|---|
| Bütün coinler | %37 | %14 | %7 |
| Taramanın en iyi %10'u | %54 | %29 | %16 |

Daha erken an (zincirde 5.–40. curve alıcısı, lansmandan saniyeler sonra) isabeti artırmıyor. Mutlak oranlar daha
düşük, çünkü çöp lansman çok. **Fomo'da alıcı gelmesi kendisi güçlü bir süzgeç.**

### 3.3 Strateji: tarama + "1 saat tut"
`scripts/exit_search.py`. Eski `scan_trade.py` sonuçları geçersiz, aşağıya bak.

**Kurulum:**
- **Seçim:** Fomo'da 3. alıcı anında, sadece Fomo akışı özellikleriyle gradient boosting puanı. Her gün sadece önceki
  günlerle yeniden eğitilir (kayan pencere). Günün eşikleri önceki 2 günün puanlarından.
- **Giriş:** 30 sn sonra havuz fiyatından, $100 ile. Komisyon ve kayma dahil.
- **Izgara:** 915 çıkış stratejisi denendi: kademeli kâr alma, iz süren stop %20-60, zarar-kes 0,5x/0,7x, en uzun
  tutma 1 saat - 7 gün. Test günleri 22 Eylül - 2 Ekim (9 gün, taze veri dahil).
- **Çıkış seçimi de dürüst:** her gün önceki günlerde en iyi olan strateji uygulandı.

**Sonuç:** Bu seçim neredeyse her gün "**hiç kısmi satış yok, stop yok, 1 saat tut, sonra sat**" oldu.

| Grup | Dürüst (kayan) seçim | 1 saat tut | En iyi %5 hariç | Medyan | Kârlı | Taze dönem |
|---|---|---|---|---|---|---|
| Taramanın en iyi %10'u (237 işlem) | **+$50 ±35** | +$67,8 (9/9 gün artı) | +$9 | −$8 | %40 | +$76 (15 işlem) |
| Taramanın en iyi %20'si (682 işlem) | **+$27 ±14** | +$35,7 (9/9 gün artı) | −$5 | −$13 | %37 | +$33 (61 işlem) |

En iyi %10'da tutma süresine göre: 15 dk +$40 · 30 dk +$62 · **60 dk +$68** · 2 saat +$57 · 6 saat +$46. 24 saatten
uzun tutmak +$20 civarına düşüyor.

**Yorum:**
- Bu bir **"piyango" yapısı**. İşlemlerin çoğu küçük zararla kapanıyor (medyan −$8). Kârı, seçilenlerin ~%5'i
  getiriyor: ilk saat içinde 15-25x yapan coinler, işlem başı +$1.000-2.400.
- En iyi %5 çıkarılınca en iyi %10 hâlâ +$9, en iyi %20 −$5.
- Kademeli satış, iz süren stop ve zarar-kes bu büyük kazananları erken kestiği için ortalamayı düşürüyor.
- Seçimsiz girmek her kuralda eksi.
- **Sınırlar:**
  - Örnek 9 gün. Sonuç az sayıda büyük işleme bağlı; kötü bir hafta olabilir.
  - Sığ havuzda 15-25x'te satışın gerçek kayması tahminden kötü olabilir.

**Düzeltilen hata (2 Ekim):** `scan_trade.py`'deki "yarısı 2x + kalanı iz süren stop" hesabı, fiyat 2x'e varmadan %30
düşse bile pozisyonun 2x'e kadar tutulduğunu varsayıyordu (gelecek bilgisi). Daha önce raporlanan +$26-32 bu yüzden
şişmişti; doğru simülasyonda aynı kural −$1 ile −$3 arası. Kod düzeltildi.

## 4. Denenip bırakılanlar (neden)

| Deneme | Sonuç |
|---|---|
| DexScreener 5-30 dk örnekleriyle ölçüm (`/karne`, `/hedef` vb.) | Zincir fiyatlarına göre 2-3 kat iyimser → silindi |
| Momentum v1/v2, rug riski, ÇIK/DİKKAT | Zincir verisiyle kanıtlanmadı; ÇIK %43 yanıldı → silindi |
| Mezuniyet öncesi Pons takibi | Medyan 1 saat sonra 0,7x → kapalı, sonra silindi |
| Sadece Fomo akışıyla "2x olur mu", 72 saat tutarak | Örnek dışı başa baş / eksi |
| Cüzdan kopyalama | Cüzdan başarısı kalıcı değil (korelasyon ~0,1) |
| GoPlus (dış güvenlik API'si) | Pons coinleri aynı şablon; geçmiş testine yaramıyor (canlıda ek kontrol olabilir) |
| Geliştirici geçmişi | Geliştiricilerin %88'i tek coin çıkarıyor; ayırmıyor |
| Zincirde çok erken an (curve) | İsabet artmıyor (3.2) |
| Seçimsiz "her coine gir" | Her çıkış kuralında eksi ya da ~0 |
| X/Twitter sosyal sinyaller | Ücretli → şimdilik yok |

## 5. Ölçüm kuralları (zor yoldan öğrenildi)

Her biri bir kez sahte kâr üretti:
1. **Gelecek bilgisi yok:** Özellik sadece o ana kadarki veriden. Havuz derinliği bile sinyalden **önceki** işlemlerden.
2. **Giriş gelecekteki bir işleme bağlanmaz.** "30 sn sonraki alımın fiyatı" demek, sonra kimse almadıysa işlemi
   saymamak demektir. Giriş o anki havuz fiyatından olur.
3. **Seçim sızıntısı:** "İleride Fomo'ya gelen coinler" gibi bir evren gelecek bilgisidir. Erken an testinde bütün
   lansmanlar kullanılır.
4. **Düşüşler ve çıkış değeri tüm işlemlerden okunur.** Coinler satışlarla çöker; sadece alım fiyatı kaybı gizler.
   Ölü coin (6 saat işlem yok) yarı fiyat.
5. **Yol sırası korunur:** Bir kural iki olayı içeriyorsa (ör. 2x'te sat + iz süren stop) hangisi önce olduysa o
   uygulanır. "Sonunda 2x'e ulaştı" diye önceki stopu yok saymak gelecek bilgisidir.
6. **Yükseliş iki ardışık alımla tutulmalı.** Fomo toplu işlemlerinde ~%5 satış fiyatı bozuk; tek basım hedefi
   geçemez, coin başına tavan 100x.
7. **Komisyon en az $0,95** (%0,5 değil). Kayma hesaba katılır.
8. **Doğrulama:** Ayrı test dönemi, kayan pencere, gün gün artı/eksi ve hata payı. "En iyi %1 hariç" ile şans kontrolü.

## 6. Veri ve araçlar

**Arşiv:** GitHub `veri` dalı, günlük parquet (1-3 Eylül + 17 Eylül-1 Ekim; 3-17 Eylül eksik, indirilmeyecek).
Yeni oturumda araştırma veritabanını kurmak:
```
git fetch origin veri && git worktree add /tmp/veri origin/veri
python scripts/data_import.py /tmp/veri fomo.db
python scripts/fomo_supply.py fomo.db
python scripts/pons_launches.py fomo.db
```
Araştırma için venv'e `numpy pandas pyarrow scikit-learn` gerekir.

**Betikler (`scripts/`):**

| Durum | Betik | Ne yapar |
|---|---|---|
| Veri | `fomo_download.py` | Zincirden bütün Fomo işlemleri (günde ~300k) |
| Veri | `data_export.py` / `data_import.py` | `veri` dalı arşivi |
| Veri | `fomo_supply.py` | Coin arzları (FDV için) |
| Veri | `pons_launches.py` | Bütün Pons lansmanları (token, curve, geliştirici) |
| Veri | `transfer_download.py` | Coinlerin ilk saat token transferleri (holder özellikleri) |
| Veri | `curve_download.py` | Pons curve işlemleri (`all`: bütün lansmanlar) |
| **Güncel** | `winner_study.py` | Fomo 3./5./10./20. alıcı anları + özellikler + sonraki zirve |
| **Güncel** | `transfer_features.py` | Bu anlara holder özellikleri ekler |
| **Güncel** | `rise_detect.py` | "Ciddi yükseleni ayırabiliyor muyuz" raporu |
| **Güncel** | `exit_search.py` | Kayan pencereli tarama + 915 çıkış stratejisi ızgarası, dürüst çıkış seçimi |
| Güncel | `scan_trade.py` | Tarama + birkaç çıkış kuralı (`kayan`, `taze` modları); 2 Ekim'de iz süren stop sırası düzeltildi |
| Güncel (olumsuz sonuç) | `curve_study.py` / `curve_report.py` | Zincirde çok erken an testi |
| Betimleyici | `coin_lifecycle.py` | Coin yaşam döngüsü istatistikleri |
| Yardımcı | `rise_build.py` | Maliyet/kayma/havuz derinliği fonksiyonları (diğer betikler kullanıyor); kendi tablosu eski "2x olur mu" çalışmasından |

**Çalışma sırası (güncel boru hattı):**
```
winner_study.py fomo.db winners.parquet
transfer_download.py fomo.db winners.parquet
transfer_features.py fomo.db winners.parquet winners_tx.parquet
rise_detect.py winners_tx.parquet
exit_search.py fomo.db winners_tx.parquet [taze_winners.parquet]
```

## 7. Yol haritası

1. ~~Taze veriyle son sınav~~ (2 Ekim: yön tuttu, örnek küçük). Birkaç gün sonra aynı testi daha uzun taze
   veriyle tekrarlamak: `fomo_download.py` → `data_merge.py` → `winner_study.py ... <başlangıç> <bitiş>` →
   `scan_trade.py ... taze <yeni.parquet>`.
2. **Bota "kayıt modu":** Fomo 3. alıcısında tarama puanı (sadece akış özellikleri, `flow.py`) hesaplansın, bildirim
   göndermeden kaydedilsin. Sonuç zincirden ölçülsün.
3. Tutarsa: bildirim (puan, kriterler, "yarısı 2x, kalanı iz süren stop" hatırlatması).
4. Sonraki aşama (kullanıcı onayıyla): pozisyon büyüklüğü ve risk yönetimi, gerçek işlem takibi, canlı işlem.
