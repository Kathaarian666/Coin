# Fomo Coin Tarayıcı — Proje Belgesi

Son güncelleme: 3 Ekim (genel denetim, §0 D-maddeleri). Bu belge projenin tek özetidir: ne yapmak istiyoruz, plan, nerede
duruyoruz, ne biliyoruz, neyi bıraktık. Eski ayrıntılar ve silinen betikler git geçmişinde.

## 0. Açık işler (kullanıcı kuralı, 3 Ekim: hiçbir iş atlanmaz)

Kural: konuşulan bir iş bitmeden yeni işe geçilmez. Kullanıcı "şimdilik geç" derse iş burada **ertelendi** olarak
kalır ve her adım sonunda / uygun anda kullanıcıya hatırlatılır. Yeni oturumda önce bu listeye bakılır; iş bitince
satırı silinir (sonucu ilgili bölüme yazılır).

| # | İş | Durum |
|---|---|---|
| A1 | Holder'lı ikinci model kâğıt testte (3 Ekim, §3/§4.6): sunucu güncellenince başlar; değerlendirme A4 ile birlikte | A4'te bakılacak |
| A2 | Taze gün testi: yapıldı (§4.6, 2x %80, 11 seçim); arşiv 3 Ekim 08:14'e kadar. Her gün yeni günler eklenip tekrarlanacak (kâğıt testle birlikte) | sürekli |
| A4 | Kâğıt test değerlendirmesi (~8-10 Ekim): `/karne` ↔ simülasyon; `/canli` açılsın mı | tarihi bekliyor |
| A8 | Pump.fun araştırması (Robinhood'daki adımlar: güvenlik, yükseliş kriterleri, simülasyon, kâğıt test). 4 Ekim: ön çalışma başladı (§4.5c); tam ölçüm 5-7 gün veriyle (~9-10 Ekim) | sürüyor |
| A7 | BNB toplayıcı sunucuda çalışıyor (3 Ekim, `fombnb`: dakikada ~110-250 Fomo işlemi, 10-45 flap.sh lansmanı); Base bekletiliyor (kullanıcı onayı; geçmişi istendiğinde indirilir) | Base: ertelendi |
| A9 | `veri` dalı büyüyor (~120 MB/gün: pump.fun + BNB) → ~1 ay sonra GitHub'ın önerdiği sınıra (~5 GB) yaklaşır; daha sıkı biçim (adres sözlüğü, imza sütununu atma) ya da başka depolama gerekecek | **ertelendi** (kullanıcı, 4 Ekim: "acelesi yok, ileride"); ~1 Kasım'dan önce hatırlatılacak |
| D7 | (kullanıcı: "sonra") Denetim: 3. adım karar kapısı ("haftada kasa 2x") geçilmeden kâğıt teste geçildi (kullanıcı kararı); son hafta masraflı 1,66x, taze günler ~1,3x/hafta → A4'te hedef tutmazsa ne yapılacağı kararlaştırılmalı | A4 ile |
| D8 | Robinhood gece arşivi kuruldu (bot gördüğü her Fomo işlemini `fomo_log`'a yazar, gece `robinhood/<gün>/`); haftalık yeniden eğitim `scripts/retrain.py` (oturumda; sunucuda değil). İlk eğitim A4'ten sonra (karne iki modeli karıştırmasın), sonra haftada bir | A4 sonrası |
| A10 | Çıkış anındaki gerçek satış değerini zincirde ölçmek (eski blokta satış simülasyonu) → kural taramasını gerçek değerle tekrar, sonra final sınavı (1 Ekim+) (§4.4b) | konuşulacak |
| K3 | `VERI_GITHUB_TOKEN` ~1 Ocak'ta dolar → yenileme hatırlatması (Aralık sonu) | Aralık |

## 1. Amaç (kullanıcı kararları, 2 Ekim)

Bot, Fomo uygulamasında (Robinhood Chain) **yeni çıkan coinler** arasından **yükselme ihtimali en yüksek olanları**
bulur, güvenlik taramasından geçemeyenleri sessizce eler, kalanları kullanıcıya rapor olarak gönderir.
**Alıp almama kararı kullanıcınındır.** İşlemler elle, Fomo'da yapılır; bot alım-satım yapmaz.

| Konu | Karar |
|---|---|
| Rapor | **Güven puanı** + **2x ihtimali** (model puanı ve detayı: puanı en çok etkileyen nedenler) + bildirim fiyatı |
| Başarı | Coin **bildirim anındaki fiyatın brüt 2x'ine** ulaşır. Süre önemsiz, üst sınır yok. Kayma ve komisyon başarı tanımına girmez. |
| Bildirimden sonra | Bot coin 2x'e ulaşınca **"2x oldu"**, likidite çekilirse **"⚠️ likidite çekiliyor"** haberi verir. Satış kararı kullanıcının. |
| Bildirim sayısı | Mümkün olduğunca az. Eşik, backtest'in "günde kaç bildirim · yüzde kaçı 2x" tablosuna bakılarak birlikte seçilir. |
| Güvenlik — eleme | **Sadece satılamama elenir:** honeypot ya da toplam alım+satım vergisi **≥ %10**. Satılabilirlik doğrulanamazsa coin elenmez, raporda "⚠️ satılabilirlik doğrulanamadı" yazar. |
| Güvenlik — rapor | Diğer 14 kontrol **eleme yapmaz**, raporda tek tek görünür (bilinmeyen "bilinmiyor" yazar). Ayrıca 0-100 **güven puanı**; her kontrolün puana etkisi geçmiş veride tuzak oranını ne kadar artırdığına göre belirlenir. |
| Güvenlik — kaynak | Kendi zincir kontrollerimiz + GoPlus + GeckoTerminal + DexScreener (hepsi ücretsiz, Robinhood Chain'i destekliyor). Dış kaynaklar yeni coinlere geç yetişiyor (40 dk'lık coinlerin çoğunda honeypot "bilinmiyor") → asıl yük zincir kontrollerinde, dış kaynak ikinci görüş. |
| "Tuzak" tanımı | Güvenlik ölçümünde kötü coin = **satılamayan** (honeypot/yüksek vergi) ya da **rug** (likidite çekildi / fiyat kısa sürede %90+ çöktü, 2x görmeden). Normal sönen coin güvenlik değil, yükseliş konusu. |
| Kriterler | Model puanı kullanılabilir; kullanıcı puanın detayını görür. |
| Veri | Her kriter **gerçek Fomo zincir verisiyle** backtest edilir; DexScreener vb. tahmini veri karar ölçüsü olmaz. |

**3. adım (simülasyon) kararları (2 Ekim):** tutar güvene / 2x ihtimaline göre değişir · 2x'te **yarısı satılır**, kalanı
devam eder · **%50 düşüşte satılır** (zarar-kes) · hedef **haftada kasayı 2x** (kasa belli değil → sonuç kasaya oranla) ·
tablo **brüt ve masraflı** (Fomo komisyonu yön başına en az $0,95 + kayma) yan yana. Varsayılan tutar: 2x ihtimali
yüksek → kasanın %4'ü, orta → %2, düşük → %1 (kullanıcı değiştirebilir). Kalan yarı için üç kural yan yana: zirveden
%50 düşünce sat / 24 saat sonra sat / hiç satma. **Bildirimden sonra "⚠️ likidite çekiliyor" uyarısı da olacak**
(kullanıcı istedi; 4. adım).

**2. adım kararları (2 Ekim; 3 Ekim'de değişti → bildirim anı 5. alıcı, 20 kriter, en iyi %2, §4.4 C+D):** bildirim anı = Fomo'da **3. alıcı** · modelde **17 kriter** (§4.2'deki güçlü/orta olanlar;
etkisiz 9'u çıktı) · tutar kasanın %4 / %2 / %1'i (2x ihtimaline göre) · kullanıcının **tepki süresi ~30 sn** (simülasyonun
asıl ölçüsü; 60 sn üstü zararlı çıktı → bildirim hızlı olmalı, Fomo'da coini açan link) · otomatik alım **yok**.

**Kapsam (2 Ekim; 3 Ekim'de değişti → kullanıcı: "önceliğimiz pump.fun, en az Robinhood kadar iyi"; BNB verisi de toplanıyor, Base ertelendi, §2 adım 6):** şimdilik **sadece Robinhood Chain**. Fomo'da Solana (pump.fun), BNB, Base vb. zincirlerden de coin
var; bunları görmüyoruz, yani kısıtlı bir havuza bakıyoruz. Robinhood Chain'de sistem kanıtlanınca aynı yöntem diğer
zincirlere taşınacak. **Kullanıcı istedi: her adım sonunda bunu hatırlat.**

Değişmeyen eski kararlar: sadece ücretsiz kaynaklar (X/Twitter API yok), Fomo "thesis" yazıları kullanılmaz.

**Neden yeniden hizalandı:** 24–27 Eylül'deki bot bu hedefe yakındı (güven + momentum puanı, bildirim). Sonra
DexScreener ölçümleri sahte sonuç üretti, bot sadeleştirildi ve araştırma "botun kendisi alıp 1 saat tutsa kaç $
kazanır" sorusuna kaydı (çıkış stratejileri, kayma, $ kâr). Kullanıcı satışa botun karışmasını istemiyor; o işler
bırakıldı.

## 2. Plan (her adımın sonunda durup kullanıcıyla bakılır; onaysız sonraki adıma geçilmez)

| Adım | Ne | Durum |
|---|---|---|
| **0** | Temizlik + bu belge + veri arşivini güncelleme | bitti (2 Ekim) |
| **1** | **Güvenlik kriterleri (birlikte).** Her kontrol için: ne kontrol ediyor, neyi eliyor, geçmiş veride kaç coini eledi, elenenler gerçekten kötü müydü. Ekle/çıkar; hangisi **eler**, hangisi raporda **yazar**. | bitti (2 Ekim): §1 kararlar, §4.1 ölçüm |
| **2** | **Yükseliş kriterleri (backtest ile, birlikte).** Aday kriterler tek tek: 2x oranını ne kadar artırıyor, görmediği günlerde tutuyor mu. Bildirim anı karşılaştırması (Fomo'da 3./5./10. alıcı). Kriter listesi + model. | bitti (3 Ekim): 5. alıcı, 20 kriter (§4.4 C+D), en iyi %2; holder'lı ikinci model kâğıt testte (§4.6) |
| **3** | **Simülasyon (karar kapısı).** Güvenlik elemesi + model uçtan uca geçmiş veride: günde kaç bildirim, kaçı 2x, girseydik sonuç ne olurdu. "Yeterince kâr" tanımı ve 2x olmayanların nasıl sayılacağı bu adımda birlikte belirlenir. Yetmezse 1/2'ye dönülür. | yapıldı, **kapı açık kaldı**: hedef (haftada 2x) son haftada tutmadı (masraflı 1,66x); kullanıcı kâğıt teste geçmeyi seçti → karar A4'te (§0 D7) |
| **4** | **Bot.** Bildirim (güven + 2x ihtimali + nedenler), "2x oldu" haberi, karne. Kriterler kesinleşmeden bota dokunulmaz. | **sürüyor**: kâğıt test kuruldu (3 Ekim, §3) |
| **5** | **Canlı izleme.** Karne (bildirimlerin kaçı 2x yaptı) simülasyonla karşılaştırılır. | kâğıt test sürüyor (A4: ~8-10 Ekim) |
| **6** | **Diğer zincirler** (Solana/pump.fun, BNB, Base…): Fomo'daki diğer zincirlere aynı yöntem; her zincir için ayrı veri ve güvenlik kontrolleri. | **sürüyor, öncelik pump.fun** (3 Ekim, kullanıcı: "pump.fun'da en az Robinhood kadar iyi"): pump.fun ve BNB verisi toplanıyor (§4.5, §4.5b); araştırma ~9-10 Ekim (A8); Base ertelendi |

## 3. Şu anki durum

**Sunucudaki bot (`rhscanner/`, systemd servisi):**
- (Eski akış, bildirimleri kapalı) Fomo işlemlerini izliyor. Bir coin 10 dakikada yeterli alıcıya (`/minalici`) ve
  hacme (`/minhacim`) ulaşınca güven taraması yapıyor, skor `/minskor` üstündeyse rapor gönderiyor — bildirimler
  kapalıyken de analiz yapıyor (§0 D6).
- Güven taraması: satılabilirlik, honeypot simülasyonu, kontrat, likidite, V4 hook, holder, geliştirici geçmişi,
  sniper/bundle, sahte hacim (Fomo churn). Ayrıntı: `README.md`. 1. adımda tek tek gözden geçirilecek.
- **Kâğıt test (3 Ekim, `paper.py`, `/karne`, kullanıcı kararı "b"):** Fomo'da 5. alıcıya ulaşan her yeni coin 20
  kriterle (§4.4 C+D) puanlanır; son 2 günün puanlarının en iyi %2'si seçilir; her seçim için sanal işlem (30 sn sonra
  alış, 2x'te yarısı, iz kuralı, %50 zarar-kes, komisyon + kayma, $1.000 kasanın %4/%2/%1'i). Para harcanmaz, mesaj
  yok (`/kagitbildirim ac` ile açılır). Model `scripts/paper_export.py` ile eğitilir (JSON = sklearn birebir; canlı
  kriter kodu araştırma tablosuyla 300 coinde birebir); ilk alıcı geçmişi `paper_book.json`'dan başlar, canlıda büyür.
  Satış $'ı artık canlıda da USDG transferinden okunuyor (`fomo.fetch_sell_usd`). Yeniden başlatmada açık sanal
  işlemler kaybolur (sonuçsuz kapanır). Eski kayıt modu (`scan.py`, `/kayit`) silindi.
- **İkinci model (+ holder, 3 Ekim, §4.6, kullanıcı "ekle"):** aynı coinler 20 kriter + 8 holder kriteriyle de
  puanlanır (`paper_model_h.json`, tablo `paper_log_h`), kendi son 2 günlük en iyi %2'si ve kendi sanal işlemleri;
  `/karne` ikisini alt alta gösterir. Holder bilgisi coinin Transfer loglarından (ilk Fomo işleminden 1 saat öncesi /
  lansmandan 5. alıcının bloğuna; coin başına ~0,2-7 sn); 5. alıcı ilk Fomo işleminden 1 saatten geç geldiyse boş
  (araştırmadaki gibi). Canlı hesap araştırma tablosuyla 300 coinde birebir. Gerçek bildirim (`/canli`) ana modelle.
- **Denetim düzeltmeleri (3 Ekim, §0 D1-D6, D10; kullanıcı onayıyla):** güven raporu §1 kararına göre yeniden yazıldı
  (`safety.py`: tek güven puanı = model; 14 kontrol sabit sırayla ✅/⚠️/❔; GoPlus + GeckoTerminal + DexScreener ikinci
  görüş, `/check` de aynı rapor) · bildirimde ham birim fiyatı yerine piyasa değeri ve 2x hedefi · "2x oldu" 30 gün
  izlenir, yeniden başlatmada kaybolmaz · takipteki coinler ve sanal işlemler veritabanında, yeniden başlatmada geri
  gelir (kaldığı bloktan devam ederse ısınma atlanır) · eski akış bildirimleri kapalıyken analiz yapmaz · RPC 10M blok
  sınırı: uzun log aralıkları bölünüyor (lansman/geliştirici/hook kontrolleri bu yüzden hep "bilinmiyor" çıkıyordu) ·
  bildirim sayısı en iyi %2 (günde ~6-10) kullanıcı onayladı.
- **Sunucu belleği (3 Ekim, D9):** 952 MB'ın ~360'ı kullanımda; 2 GB swap dosyası eklendi (`/swapfile`, `/etc/fstab`). Ubuntu güncellemeleri için yeniden başlatıldı (K2), üç servis kendiliğinden açıldı.
- **Gerçek bildirim hazır, kapalı (3 Ekim, `live.py`, `/canli ac|kapat`):** kâğıt testin seçimi → satılamama elemesi
  (Pons coini geçer; diğerleri V4 satış simülasyonu: geri dönerse ya da vergi ≥ %10 ise elenir; havuz/alıcı
  bulunamazsa "⚠️ doğrulanamadı" ile gider; coin başına 5-12 sn) → hızlı mesaj (2x ihtimali ~%61, puanı en çok
  yükselten 3 kriter, GeckoTerminal linki) → yanıt olarak güven raporu + model güven puanı (`trust_model.json`,
  §4.1 tuzak modeli, AUC 0,84) → sonra "2x oldu" ve V4 havuzundan likidite çekilirse uyarı (ilk 6 saat).

## 4. Şimdiye kadar bilinenler

(Bu girişteki maddeler eski araştırma, 17–28 Eylül; fiyat = son 3 alımın ortancası, sonradan hatalı bulundu §6.2.) Bunlar yön gösterir; 2x tanımı (bildirim fiyatından, süresiz) ile 2. adımda **yeniden ölçülecek**.
- Günde ~2.000 yeni coin Fomo'da görünüyor, Pons'ta günde ~6.500 lansman. Fomo coinlerinin %86'sı hiç 10 alıcıya
  ulaşmıyor. 72 saat sonra medyan fiyat ilk fiyatın ~%30'u.
- Fomo coinin küçük bir parçası: Fomo'da 3. alıcı geldiğinde coinin zincirde zaten ~40+ holder'ı var; holder'ların
  %9-20'si Fomo kullanıcısı.
- Ciddi yükselişler var: ilk Fomo fiyatından günde ~44 coin 10x+ yapıyor. 2x'lerin 2/3'ü ilk 30 dakikada geliyor;
  2x yapanlar önce neredeyse düşmüyor (dip medyanı 0,98x).
- Yükselenleri 3. alıcı anında ayıranlar: hızlı, büyük, dağınık alım (işlem başına $, k. alıcıya hız, en büyük
  alıcının payı düşük), henüz satan yok, küçük FDV, lansmana yakınlık; holder tarafında ilk 10 cüzdan payı,
  transfer yoğunluğu, sniper payı (küçük katkı). Ayırmayanlar: geliştirici geçmişi, yeni cüzdan oranı, genel piyasa,
  cüzdan kopyalama.
- Model puanının en iyi %10'u (3. alıcıda, sonraki 72 saatte zirve, fiyat = son 3 alımın medyanı):

| | ≥2x | ≥5x | ≥10x |
|---|---|---|---|
| Bütün coinler | %37 | %14 | %7 |
| Model puanının en iyi %10'u | %54 | %29 | %16 |

- Daha erken an (zincirde 5.–40. curve alıcısı) isabeti artırmıyor; Fomo'da alıcı gelmesi kendisi güçlü bir süzgeç.

### 4.1 Güvenlik ölçümü (1. adım, `scripts/security_study.py`, 2 Ekim)
18 Eylül–1 Ekim, Fomo'da 3. alıcıya ulaşan 7.714 yeni coin (en az 24 saat izlenmiş). Tuzak oranı %3,6 (rug %1,9,
satılamayan %1,7). Pons coinlerinde satılamayan %0 (beklenen; etiket tutarlı).

| Kontrol (3. alıcı anında) | Coin | Tuzak | Diğerleri |
|---|---|---|---|
| Pons değil | 2.371 | %7,6 | %1,8 |
| Fomo'da 2+ farklı satıcı | 945 | %0,4 | %4,0 |
| Nadir kontrat (aynı fonksiyon seti < 5 coinde) | 378 | %15,3 | %3,0 |
| Proxy (yükseltilebilir) | 35 | %31 | %3,5 |
| Sahibi var (owner) | 747 | %11 | %2,8 |
| mint fonksiyonu | 26 | %15 | %3,5 |
| trading aç/kapa fonksiyonu | 54 | %44 | %3,3 |
| Geliştirici 3+/10+ coin | 1.022 / 733 | %2,1 / %2,3 | %3,8 / %3,7 (ayırmıyor) |
| Fomo churn ≥ %40 | 75 | %2,7 | %3,6 (ayırmıyor) |

- Bir Pons dışı launchpad şablonu (53 coin) %23 satılamayan; 342 farklı kontrat şablonu var, 253'ü tek coinlik.
- "trading aç/kapa" coinleri %65 2x görünüyor ama %44'ü tuzak: satılamayan coinin 2x'i anlamsız.
- Fomo'da erken satış olan coinlerde 2x oranı düşük (%13 vs %30): güvenlik değil, 2. adım için not.
- Holder/lansman/likidite/hook (`scripts/security_extra.py`; holder 6.422 coinde ölçülebildi = transfer kaydı
  lansmandan başlayanlar). Pons ve Pons dışı ayrı bakıldı (Pons'ta tuzak %1,8, değilde %8):

| Kontrol | Pons: tuzak (işaretli / diğer) | Pons değil: tuzak (işaretli / diğer) |
|---|---|---|
| İlk 10 cüzdan > %50 | %0,5 / %2,3 | %7,0 / %8,3 |
| Tek cüzdan > %15 | %1,0 / %2,1 | %7,4 / %8,3 |
| Geliştirici > %5 | %2,0 / %2,0 | **%14 / %6,9** |
| Geliştirici ilk aldığının yarısını sattı | %1,8 / %2,1 | %4,1 / %8,6 |
| Bundle > %10 / Sniper > %25 | ayırmıyor | az coin, ayırmıyor |
| Likidite < $1k (Fomo fiyat etkisinden) | %2,5 / %0,9 | %7,4 / %10 (karışık) |
| Hook yok (düz V4 havuzu) | — | **%14,6 / %4,8** |
| Pons hook'u (Pons V2 listesinde olmayan Pons coinleri, 497) | — | **%0 / %12** |
| Başka hook / yükseltilebilir hook | — | %9,1 / %8,4 · %2,9 / %8,7 (ayırmıyor) |

  Klasik rug işaretleri (yoğun holder, bundle, sniper, geliştirici satışı) bu erken anda tuzağı **ayırmıyor**. Ama
  yükselişi ayırıyor: ilk 10 cüzdan > %50 olanlarda 2x %4,8 (diğerleri %31), tek cüzdan > %15'te %15 (%30) → 2. adım.
- **Güven puanı denemesi:** ayıran kontrollerle lojistik model, 26 Eylül öncesiyle eğitildi, sonrasında (2.732 coin)
  sınandı. AUC 0,83. Puan = 100 × (1 − tuzak olasılığı / 0,5):

| Puan | Coin | Tuzak | 2x |
|---|---|---|---|
| 0-49 | 37 | %59 | %40 |
| 50-69 | 16 | %19 | %44 |
| 70-84 | 281 | %7,1 | %30 |
| 85-100 | 2.398 | %1,3 | %26 |

  En çok etki edenler: Pons hook'u ve Fomo'da 2+ satıcı (güven artırır); kontratın sahibi olması, trading aç/kapa,
  başka hook ya da hook yok, nadir kontrat (güven düşürür).
- **Sahiplik düzeltmesi (3 Ekim, kullanıcının `/check` denemesinden):** "sahibi var" iki ayrı grubu karıştırıyordu.
  `0xeb7c0347...` ~1.500 Fomo coininin ortak sahibi (Pons/Doppler hook'lu launchpad coinleri): 572 ölçülen coinde
  tuzak **%0**; başka bir sahibi olan 179 coinde tuzak **%46**; sahipsiz %2,8. Güven modeli ortak sahip hariç tutularak
  yeniden eğitildi (`scripts/trust_export.py`, eski işaretlerle 0,838 = eski model; yeni test AUC 0,845; "sahip"
  katsayısı 1,26 → 2,58). Puan 0-50: tuzak %50 · 70-85: %8,9 · 85-100: %1,9. Raporda ortak sahip ✅.
- **V4 satış simülasyonu (`contracts/V4SellProbe.sol`, `scripts/sell_probe_study.py`, 2 Ekim):** gerçek bir holder'ın
  adresine eth_call state override ile konan program coini V4 havuzuna satıyor (para harcanmaz). Çalışıyor; geçmiş
  blokta sadece dRPC'de (ana RPC eski durumu tutmuyor), canlıda `latest` ile. Bulgu: "satılamayan" etiketli 13 Pons
  dışı coinin **12'si bildirim anında satılabiliyordu**; çoğunda 1 saat içinde satış "çıktı 0" (likidite çekildi = rug),
  2'sinde satış sonradan kilitlendi. Yani bildirim anında honeypot nadir; asıl tuzak bildirimden sonraki ilk saatte
  likiditenin çekilmesi → bildirim anında ancak dolaylı işaretlerle (güven puanı) tahmin edilir. Eleme kuralı
  (honeypot / vergi ≥ %10) yine simülasyonla uygulanır (4. adım).
- **Botta bulunan açık — düzeltildi (3 Ekim):** `checks/contract.py` sadece 45 baytlık EIP-1167 klonu tanıyordu;
  44 baytlık türler (714 coin, 33 asıl kontrat; zincirde görülen `3d3d3d3d363d3d37...`) artık tanınıyor
  (`minimal_proxy_target`, gerçek coinlerde araştırmayla aynı şablon).

### 4.2 Yükseliş ölçümü (2. adım, `scripts/rise_study.py`, 2 Ekim)
18 Eylül–1 Ekim, en az 24 saat izlenmiş yeni coinler. 2x = bildirimdeki son alım fiyatının 2 katı, iki ardışık alımla,
süre sınırı yok. Eğitim 26 Eylül öncesi, test 26 Eylül–1 Ekim (6 gün).
- 2x'e ulaşma (3. alıcıdan): medyan 17 dk, %71'i ilk 1 saatte, %3'ü 24 saatten sonra.
- Bildirim anı: 3. alıcı (527 coin/gün, 2x %26, ilk Fomo işleminden 3 dk sonra) · 5. alıcı (385, %30, 6,5 dk) ·
  10. alıcı (265, %34, 12,5 dk). Aynı sayıda bildirimde model sonuçları benzer (günde ~20-30: %51 / %49 / %47) →
  en erken an olan 3. alıcı kaybettirmiyor.
- Tek tek kriterler (en kötü / en iyi beşte birlik dilimde 2x, test günleri): **güçlü** — lansmandan bu yana dakika
  (%36 / %9, genç coin iyi), 3. alıcıya kadar dakika (%40 / %14, hızlı iyi), son 10 dk alım $ (%16 / %36), işlem başına $
  (%17 / %36), FDV (%18 / %36), toplam alım $, en büyük alım $, son 5 dk alıcı, işlem sayısı (az iyi), havuz derinliği,
  ilk 10 cüzdan payı (%22 / %9), satış $ payı, ilk alıcılardan satanlar, satıcı sayısı, ilk alımdan bu yana fiyat,
  zirveden uzaklık; **orta** — en büyük cüzdan payı; **etkisiz** — geliştirici geçmişi/payı, akıllı cüzdan, saat, sniper,
  yeni cüzdan oranı, tekrar alım, en büyük alıcının payı, piyasanın genel hareketi.
- Hepsi birlikte (her gün önceki günlerle eğitilen model, sadece o gün bilinen 2x'lerle): en iyi %10 → günde 42
  bildirim, 2x %46 (±6) · en iyi %5 → 21, %51 (±9) · en iyi %2 → 8, %57 (±14) · en iyi %1 → 3, %58 (±22). Taban %24.
  Holder kriterleri (ilk 10 cüzdan, en büyük cüzdan, derinlik) 1-5 puan katıyor. 6 test günü az; üst dilimlerde hata
  payı büyük.

### 4.3 Genişletilmiş veri ve simülasyon (3. adım, 2 Ekim akşam)
- 3-17 Eylül boşluğu indirildi (`data_merge.py --fill`): 19,2 milyon işlem, 3 Eylül–1 Ekim aralıksız, 27.265 yeni coin.
  Lansman zamanları boşluk doldurulunca işlemlerden yeniden hesaplandı (eski interpolasyon 6-18 dk kaymıştı; yeni
  boşluk doldurulursa aynısı yapılmalı). 4 Eylül 13:08'de 9 dk işlem yok (Fomo duruşu ya da kayıp, önemsiz).
- **Piyasa soğuyor:** Fomo hacmi Eylül başında günde $280-500M, Eylül sonunda ~$50M. Seçimsiz 2x oranı haftalık
  %31 → %30 → %28 → %26.
- Model (17 kriterden 15'i; holder kriterleri RPC kısıtlaması yüzünden bu turda yok), 10 Eylül–1 Ekim, 22 test günü:
  en iyi %10 → günde 69 bildirim, 2x %50 (±3) · %5 → 33, %52 (±4) · %2 → 14, %55 (±6) · %1 → 8, %58 (±7).
- Kriterler büyük veride: alım $ (son 10 dk, işlem başı, toplam, en büyük), 3. alıcıya hız, fiyat yükselişi, zirveden
  uzaklık güçlü; satış payı/satıcılar, derinlik, son 5 dk alıcı, geliştirici coin sayısı orta; lansman yaşı ilk
  haftada etkisiz ama sonraki günlerde tutuyor; FDV tutmuyor (arz verisi eksik: boşluk döneminde %61).
- **Sızıntı düzeltmesi (2 Ekim gece, ölçüm kuralı 10):** arz sadece 20+ işlemli coinler için çekildiğinden FDV'nin boş
  olması "coin ölecek" demekti. Düzeltilince model: en iyi %50 → 2x %36 (önce %44) · %10 → %46 (%50) · %5 → %50 (%52)
  · %2 → %58 · %1 → %57 (seçici eşikler sağlam). FDV gerçekten güçlü bir kriter (yüksek FDV → daha çok 2x).
- **Simülasyon (`trade_sim.py`), sızıntısız:** 22 günlük bileşik sonuç yanıltıcı; dürüst görünüm hafta hafta, kasa her
  hafta $1.000'dan, 30 sn gecikme, "iz" kuralı, **masraflı** (sızıntılı eski tablo sıcak haftada 10x gösteriyordu):

| Seçim | 10-16 Eylül | 17-23 Eylül | 24-30 Eylül |
|---|---|---|---|
| En iyi %10 (günde ~69) | 0,76x | 0,27x | 0,47x |
| En iyi %5 (~34) | 0,77x | 0,95x | 1,06x |
| **En iyi %2 (~14)** | **1,10x** | **1,11x** | **1,65x** |
| En iyi %1 (~7) | 1,08x | 0,86x | 1,32x |

  En iyi %2'de: 2x %53, %50 zarar-kes %36. Beklenen: haftada yaklaşık **+%10-65**, hedef 2x değil. Çok bildirim
  masrafta eriyor. Holder kriterleri (transfer verisi) henüz eklenmedi.

### 4.4 Farklı açılar (3 Ekim gece; kullanıcı: kâr yetersiz, "farklı gözle bak"; sıra A → B → D → C)
- **A. Modele işlemin net getirisini öğretmek (`scripts/profit_study.py`): işe yaradı.** Etiket: kullanıcının kuralları,
  30 sn gecikme, $20'lık işlem, komisyon + kayma; eğitimde test günü başladığında açık olan işlem o anki fiyatla
  değerlenir. Son fiyat = son 5 işlemin ortancası (tek bozuk satış fiyatı açık pozisyonu 100x'e kadar şişiriyordu).
  Hafta hafta, $1.000, masraflı (10-16 / 17-23 / 24-30 Eylül):

| Model, seçim | Günde | 2x | Haftalar | En iyi %1 işlem hariç, 22 gün |
|---|---|---|---|---|
| 2x modeli, en iyi %2 | 14 | %51 | 0,83 / 1,02 / 1,15x | 0,51x |
| kâr>0 modeli, en iyi %2 | 16 | %41 | 1,44 / 1,40 / 1,05x | 0,82x |
| **getiri modeli, en iyi %2** | 17 | %33 | **1,67 / 4,04 / 1,35x** | **1,42x** |
| **getiri modeli, en iyi %1** | 9 | %35 | **1,85 / 4,36 / 1,39x** | **1,80x** |

  Getiri modeli daha az 2x seçiyor ama gecikmeye dayanıklı, büyük kazananları seçiyor; işlemlerin ~%70'i zarar
  (piyango). **Kapasite sınırı:** kasa büyüyünce sığ havuzlarda kayma kârı yiyor (22 gün bileşik ≈ 1,7-2,3x).
- **B. Piyasa ısısı filtresi: işe yaramadı.** Üç tanım (son 24 saatte 1 saat içinde 2x oranı, son 6 saat Fomo hacmi,
  son 6 saat yeni coin sayısı; eşik önceki 7 günün ortancası): sıcak/soğuk anlarda ortalama getiri aynı ya da ters.

- **D. Yeni kriterler: işe yaradı.** `winner_study.py`'ye eklendi: son 60 sn alıcı ve alım payı, aynı blokta alım
  (bot), <$20 alım payı, ilk 3 alıcının daha önce ilk alıcısı oldukları coinlerde 1 saatte 2x oranı (o coinin sonucu
  1 saat sonra bilinir; `rise_study.add_history`), geliştiricinin önceki coinlerinde aynı oran. Tek tek: küçük alım
  payı (%37 / %25), ilk alıcı geçmişi (%26 / %37), son 60 sn alım payı güçlü. Çıkarma testi (en iyi %1'de 2x): eski
  15 kriter %59 → hepsi %68; ilk alıcı geçmişi ~4 puan katıyor; geliştirici geçmişi negatif → çıkarıldı (20 kriter).
  Kâr (masraflı, $1.000, 30 sn, 2x modeli):

| Seçim | Günde | 2x | Kârlı | Haftalar | 22 gün kesintisiz | En iyi %1 işlem hariç |
|---|---|---|---|---|---|---|
| **En iyi %2** | 15 | %59 | %46 | **2,30 / 5,00 / 1,64x** | 5,65x | 4,36x |
| En iyi %1 | 7,5 | %65 | %52 | 2,09 / 4,42 / 1,57x | 6,32x | 5,15x |

  D ile 2x modeli getiri modelini geçti (getiri en iyi %2: 2,38 / 5,64 / 1,27x, %1 hariç 2,16x).

- **C. Farklı giriş anları (`profit_study.py ... k`, `wave_study.py`):** en güncel hafta 24-30 Eylül, masraflı, $1.000,
  30 sn; 3 hafta = 10-16 / 17-23 / 24-30 Eylül:

| An, seçim (en iyi model) | Günde | 2x | Kârlı | 3 hafta | %1 hariç 22 gün |
|---|---|---|---|---|---|
| 3. alıcı, 2x modeli %2 | 15 | %59 | %46 | 2,30 / 5,00 / 1,64x | 4,36x |
| **5. alıcı, 2x modeli %5** | 25 | %51 | %41 | 2,23 / 4,04 / 2,23x | 2,30x |
| **5. alıcı, 2x modeli %2** | 10 | %61 | %51 | 2,58 / 4,95 / 1,66x | 4,21x |
| 10. alıcı, 2x modeli %2 | 7,5 | %61 | %53 | 1,72 / 4,45 / 1,27x | 4,04x |
| İkinci dalga, 2x modeli %2 | 3 | %53 | %49 | 0,91 / 1,13 / 1,21x | 1,19x |

  5. alıcı en iyi; ikinci dalga zayıf (bırakıldı). **Uyarı:** bu gece çok sayıda varyant aynı 22 test gününde
  karşılaştırıldı → en iyiyi seçmek şansı da seçer. Son sınav seçimde kullanılmamış yeni günlerde yapılmalı (2 Ekim
  sonrası; etiketler 24 saat sonra belli). Holder kriterleri (transfer indirmesi yavaş) hâlâ eklenmedi.

### 4.5 6. adım fizibilitesi: Fomo'nun Solana tarafı (3 Ekim)
- Fomo her Solana işlemini tek cüzdanla imzalayıp gas'ını ödüyor: `AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51`
  (ücret hesabı `HrTf9CzXR1dRH4Sof5QrpmGWwpwAf3qZzwCsEjQpXcSq`; Bitquery'nin FOMO API belgesi). İşlemlerin çoğu DFlow
  agregatöründen geçiyor. Hacim: günde ~0,9-1,2 milyon işlem (Robinhood Chain'in ~4 katı).
- **Ücretsiz canlı erişim çalışıyor** (`scripts/solana_probe.py`): genel Solana websocket'inde
  `logsSubscribe(mentions=[fee payer])` her Fomo işleminin loglarını anında veriyor (~670/dk). pump.fun TradeEvent
  loglarda çözülebilir: coin, SOL, miktar, alım/satım, kullanıcı, zaman. Tek tek `getTransaction` gerekmez (genel RPC
  buna yetmez).
- 1 dk örnek dağılımı: PumpSwap (mezun pump.fun coinleri) %53 · pump.fun curve (yeni coinler) %10 · Meteora %10 ·
  Raydium %3 · diğer %24. PumpSwap olayları da aynı yöntemle çözülebilir.
- Geçmiş veri ücretsiz toplu olarak yok (Bitquery/Helius ücretli ya da kısıtlı; Dune ücretsiz hesapla mümkün ama
  gecikmeli). Yol: şimdiden canlı toplamaya başlamak; ~1 hafta sonra Robinhood'daki aynı araştırma.
- **Toplayıcı (`rhscanner/solana.py`, sunucuda systemd servisi `fomosol`, DB `~/Coin/solana.db`):** websocket'ten
  gelen her Fomo işleminden pump.fun curve `TradeEvent` (coin, SOL, miktar, alım/satım, kullanıcı, zaman, curve'ün
  sanal rezervleri → fiyat) ve PumpSwap `BuyEvent`/`SellEvent` (havuzun coini `getAccountInfo` ile bir kez okunur)
  kaydedilir; Meteora/Raydium/diğer sadece dakikalık sayımda (`stats`). SOL/USD 5 dk'da bir (CoinGecko). Tuzaklar:
  u64 tutarlar SQLite tamsayısına sığmıyor → REAL; Anchor olay adı başka programlarda da aynı (aynı ayırt edici) →
  olay sadece o an çalışan program pump.fun/PumpSwap ise alınır (ilk denemede curve satırlarının %7'si başka
  programdandı, tarihleri bozuktu). Hacim: ~570 bin satır/gün, ~200 MB/gün ham SQLite.
- **Sunucudan araştırmaya veri (3 Ekim):** her gece 00:20 UTC `fomosol-export.timer` biten günleri
  (`rhscanner/solana_export.py`) `veri` dalına `solana/<gün>/` altına gönderir (6 saatlik `trades_<ss>.csv.gz`
  parçaları, ~50-65 MB/gün; `stats`, `sol_price`, `pools`). Token: `.env`'de `VERI_GITHUB_TOKEN` (kullanıcı kendisi
  koydu; sadece bu depo, Contents yazma). Klon sığ ve dosya içeriksiz, sadece yeni dosyalar eklenir. Okuma:
  `python scripts/solana_import.py /tmp/veri sol.db`. Elle deneme: `.venv/bin/python -m rhscanner.solana_export
  solana.db --check`.
- **Eksikler tamamlandı (3 Ekim, A5):** olaylardaki başka alanlar canlı veriyle doğrulandı (sanal − gerçek rezerv =
  tam 30 SOL / 279,9M token): curve işlemlerinde gerçek rezervler (`rsol`, `rtok`; rtok 0 = curve doldu, mezuniyet)
  ve geliştirici (`creator`); PumpSwap işlemlerinde havuzun SOL/coin rezervi (likidite, fiyat) ve coin geliştiricisi.
  Yeni `mints` tablosu: geliştirici, Fomo'da ilk görülme, **oluşturulma anı** (coin adresinin en eski işlemi = Create;
  `getSignaturesForAddress`, ücretsiz RPC 429 verdiği için arka planda 1,2 sn arayla, en çok 3 sayfa; yarıda kalırsa
  `older_than`), curve'ün boşaldığı an, `curve` (Fomo'da curve'de görüldü mü). Havuzlar da oluşturulma anı alır
  (mezuniyet). Öncelik: curve'de görülen coinler, sonra onların havuzları. Hız ~17 sorgu/dk (~24 bin/gün).
  İlk gözlem: Fomo'da curve'de işlem gören coinlerin bir kısmı dakikalar, bir kısmı aylar önce oluşturulmuş →
  "yeni coin" tanımı oluşturulma anından yapılmalı. 3 Ekim öğleden önceki işlemlerde rezerv sütunları boş.
  Holder dağılımı henüz yok (Solana'da her coin için ayrı sorgu gerekir; araştırmada ihtiyaç çıkarsa).
  Araştırma kuralları (§6) aynen geçerli.

### 4.5b 6. adım ön incelemesi: BNB ve Base (3 Ekim, §0 A7)
- **Fomo üç EVM zincirinde de aynı iki kontratla, aynı adreste ve aynı olayla çalışıyor** (entry `0xccc88a9d...`,
  executor `0xb92fe925...`, olay `0xafbab204...`): Robinhood'daki okuma kodu (`fomo.py parse_fomo_logs`) nakit
  token listesi değişerek kullanılabilir (Base: USDC `0x833589fc...` + ETH; BNB: USDC `0x8ac76a51...` + BNB).
- **BNB:** ~139 Fomo işlemi/dk (15 dk örnek; Robinhood ~67/dk, Solana ~600/dk), 15 dk'da 804 farklı alıcı, 123 coin.
  Coinlerin çoğu (90'ın 63'ü) "…7777" adresli = **flap.sh** launchpad'i (mezunlar PancakeSwap v2'de), az sayıda
  four.meme ("…4444"). **Geçmiş veri ücretsiz değil**: publicnode sadece son saatler (eskisi 403), 48.club ~1 gün,
  dRPC hemen 429, diğerleri getLogs vermiyor / 25 blok sınırı. → pump.fun gibi **şimdiden canlı toplama** gerekir
  (publicnode, adres filtresiyle son bloklar).
- **Base:** ~16 Fomo işlemi/dk (1 saat örnek; Robinhood'un ~1/4'ü), saatte ~460 alıcı, ~90 coin; havuzlar
  Uniswap V4 ve Aerodrome. **Geçmiş veri ücretsiz** (`mainnet.base.org`, 30 gün önce dahil, 500 blokluk sorgu 0,5 sn)
  → Robinhood gibi hemen indirilip araştırılabilir; ama havuz küçük.
- **İlk gece gönderimi (4 Ekim 00:23-00:28 UTC, A6/D11):** üçü de `veri` dalında. pump.fun 3 Ekim: 526.486 işlem
  (07:09-23:59, eksik saat yok), 4.011 curve + 3.671 PumpSwap coini; dakikalık sayımla karşılaştırma: curve işlemlerinin
  %100'ü, PumpSwap'ın %99,9'u kaydedilmiş (D11: kayıp önemsiz). `mints` 7.536 coin (geliştirici 6.070; oluşturulma anı
  3.380, yarıda kalan 3.195; havuz oluşturulma 162/4.435 — havuz aramaları sırada). BNB: 85.307 Fomo işlemi
  (13:24-23:59, 15 dk'dan uzun boşluk yok, yeniden başlatma dahil), 5.271 flap.sh lansmanı. Robinhood (botun gördüğü):
  92.379 işlem (15:03-23:59, boşluk yok, satışların %99'unda $). Parquet arşivi 3 Ekim 08:14'te bitiyor → 08:14-15:03
  boşluğunu `retrain.py` zincirden indirir.
- **BNB toplayıcı (3 Ekim, kullanıcı "evet"; `rhscanner/bnb.py`, sunucuda `fombnb`, DB `~/Coin/bnb.db`):** 4 sn'de bir
  publicnode'dan son bloklar (adres filtreli getLogs, 400 blokluk parçalar): Fomo olay ayakları (`fomo`), executor'a
  giden USDC (`usdc_in`, satış tutarı), **flap.sh lansmanları** (`launches`: portal `0xe2ce6ab8...` TokenCreated =
  zaman, yaratıcı, sıra no, coin, ad, sembol; bir Fomo coininin mint işleminden bulundu; 10 dk'da ~300 lansman). Blok
  zamanı iki head arasında doğrusal (BNB ~0,45 sn/blok). Ücretsiz düğüm ~1 saat log tuttuğu için toplayıcı 1 saatten
  uzun durursa o boşluk kaybolur. Canlı denemede dakikada 144-252 Fomo işlemi, 24-45 flap.sh lansmanı; 403 yok.
  Gece gönderimi `veri` dalına `bnb/<gün>/` (~61 MB/gün). Okuma: `scripts/solana_import.py /tmp/veri bnb.db --chain bnb`.
- Güvenlik tarafı zincire göre değişir (flap.sh/four.meme şablonları, PancakeSwap/Aerodrome havuzları için satış
  simülasyonu yeniden yazılmalı).

### 4.5c pump.fun ilk ölçüm (4 Ekim, §0 A8 ön çalışma; sadece 3 Ekim'in ~16 saati → yön gösterir, kesin değil)
`scripts/pump_study.py` (winner_study'nin pump.fun karşılığı, aynı ölçüm kuralları): Fomo'da ilk işlemi curve'de olan
yeni coinler, k. farklı Fomo alıcısı anı, o anki fiyat = o alımın USD/token fiyatı (SOL/USD saatlik), sonuç bütün sonraki
Fomo işlemlerinden (curve + PumpSwap). Tuzak = 1 saat içinde fiyat bildirimin %10'una iner, öncesinde 2x yok.

| An | Coin (günde) | 1 saatte 2x | 6 saatte 2x | 1 saatte tuzak | Mezun olan | Yaş medyan |
|---|---|---|---|---|---|---|
| 3. alıcı | ~1.950 | %20,4 | %22,6 | %6,1 | %21 | 3,4 dk |
| **5. alıcı** | **~1.520** | **%22,5** | **%25,6** | **%8,0** | %26 | 4,2 dk |
| 10. alıcı | ~1.090 | %22,6 | %24,3 | %13,2 | %37 | 5,9 dk |

- Havuz Robinhood'un ~5 katı (5. alıcıda günde ~1.500 coin ↔ ~300-385), 2x oranı benzer, tuzak ~2 katı.
- İlk Fomo işleminde coinin yaşı medyan 1,6 dk; %10'u 1 günden eski (sonradan canlanan) — onlarda 2x %26, tuzak %4
  (yenilerde %20 / %10).
- **Mezuniyet çöküşü:** piyasa değeri / curve doluluğu en yüksek beşte birlikte (mezuniyete yakın, ~$38k+) 1 saatte tuzak
  **%39-44** (diğer dilimlerde %0-1). Ölçüm hatası arandı: fiyat birimi mezuniyet geçişinde sürekli, PumpSwap işlem
  fiyatları havuz fiyatıyla tutarlı (yarısının altında işlem %0) → çöküşler gerçek (havuz fiyatı başlangıcın %1'ine).
- Tek kriterler (5. alıcı, 1 saatte 2x, en düşük → en yüksek beşte bir): ilk alımdan bu yana fiyat %19 → %31,
  5. alıcıya süre %26 → %15 (hızlı iyi), son 10 dk alım $ %19 → %29, son 60 sn alıcı %16 → %26; piyasa değeri ve
  curve doluluğu orta dilimde en iyi (%34-35) ama en üstte tuzak. Büyük alım $ tuzağı düşürüyor (%16 → %2).
- Sınır: sadece Fomo işlemleri görülüyor; geliştiricinin / bundle'ın Fomo dışı satışları ancak fiyattan görünür.
  Holder sorgusu (`getTokenLargestAccounts`) ücretsiz Solana RPC'de hem buradan hem sunucudan hep 429; bütün pump.fun
  işlemlerini dinlemek dakikada ~13.600 mesaj / 20 MB (günde ~29 GB, 1 GB'lık sunucu için ağır); Helius ücretsiz planı
  kayıt ister. **Kullanıcı kararı (4 Ekim): pump.fun'da holder verisi yok, fiyat + Fomo akışı kriterleriyle devam.**

### 4.4b Çıkış kuralları taraması ve satış fiyatı varsayımı (4 Ekim, kullanıcı: "farklı parametrelerle kârlılığı yukarı taşı")
`scripts/exit_study.py`: araştırmanın walk-forward seçimleri (5. alıcı, 10-30 Eylül; 1 Ekim sonrası **final sınavı,
dokunulmadı**), kural ızgarası: hedef (1,5/2/3/5x) ve hedefte satılan pay, zarar-kes, zirveden iz, süre sınırı (1-24 sa),
seçim (%1/%2/%5), tutar; masraflı, 30 sn, her hafta $1.000.
- **Olağan değerlemeyle** (çıkışta son 5 fiyatın ortancası, 6 saat işlem yoksa yarı fiyat — §6 kural 5) süre sınırlı
  kurallar çok iyi görünüyor: en iyi %2, 5x hedefte yarısı, kalan 1 saatte satılır → haftada ~9,9x (şimdiki kurallar
  2,77x). Bölge geniş (1-6 saat, 3-5x hedef hep 7-10x).
- **Hata arandı → önemli bulgu:** simülasyon, sessizleşmiş coini **son Fomo fiyatından** satabileceğimizi varsayıyor.
  Kötümser değerlemeyle (çıkıştan önceki 15 / 30 / 60 dk'da Fomo işlemi yoksa değer 0) bütün süresiz/uzun kurallar,
  **şimdiki kurallar dahil**, haftada ~0,8-1,4x'e iniyor; 1 saat sınırlı kurallar 15 dk eşikte 1,1-2,0x, 30 dk'da
  1,6-2,7x (5x hedef en iyi; üç haftanın hepsi > 1). → Kâr tahmininin büyük kısmı **çıkış anındaki gerçek satış
  fiyatına** bağlı; ne olumlu ne kötümser değerleme doğru — gerçek değer arada.
- Sonuç: (1) kısa tutma (1 saat) + yüksek hedef (3-5x) her değerlemede şimdiki kurallardan iyi; (2) mutlak kâr ancak
  çıkış anında zincirde gerçekten satılabilecek tutar ölçülerek bilinir (eski bloklarda satış simülasyonu, dRPC +
  `V4SellProbe` / Pons curve). Kâğıt test de aynı varsayımı kullanıyor (`paper.last_value`), `/karne` iyimser olabilir.

### 4.6 Taze gün testi ve holder kriterleri (3 Ekim, §0 A1/A2)
**Taze gün testi** (`scripts/fresh_test.py`): sunucudaki kâğıt test modeli (`paper_model.json`, 1 Ekim 11:18'e kadarki
anlarla eğitildi) hiç görmediği 1 Ekim 11:31 – 3 Ekim 08:14 aralığında, botun yaptığı gibi (son 48 saatin en iyi
%2'si): 537 coin 5. alıcıya ulaştı, **11 seçim; 2x %80 (8/10, 1'i henüz 24 saat izlenmedi), 1 saatte 2x %55**;
hepsinin 2x oranı %41. Kasa $1000, 30 sn, iz: brüt 1,11x, masraflı 1,07x (~1,9 günde; haftalığa çevrilince ~1,3x).
Araştırmanın walk-forward en iyi %2'si: 2x %64, son haftası %67. → Görülmemiş günlerde **2x oranı araştırmayla
tutarlı**, kasa artışı hedefin (haftada 2x) altında; örnek çok küçük (11), kâğıt test sürdükçe büyüyecek.
Arşiv: 2 Ekim'in kalanı + 3 Ekim 08:14'e kadar `veri` dalına eklendi.

**Holder kriterleri** (`scripts/transfer_download.py` → `transfer_features.py <k=5>` → `scripts/holder_study.py`):
27.112 coinin ilk Fomo işleminden sonraki 1 saatlik bütün Transfer'leri (69 milyon). 5. alıcı anında: holder sayısı,
10 dk'daki artış, top10/top1 payı, geliştirici payı / dağıttığı, sniper payı, Fomo holder payı, 10 dk transfer.
Anın bloğu 5. alıcının kendi işleminden (zamandan tahmin edilen blok anı biraz erken alıyordu: sızıntı değil, eksik
bilgi). 1 saatten geç gelen anlarda bilgi boş (o anda bilinen bir koşul; anların %89'unda bilgi var).
Aynı 22 walk-forward gün (10 Eyl – 1 Eki), botun 20 kriteri ↔ 20 + 9 holder kriteri:

| Seçim | 2x (20 kriter) | 2x (+ holder) |
|---|---|---|
| en iyi %5 (günde ~25) | %54,6 | **%62,8** |
| en iyi %2 (günde ~10) | %64,0 | **%75,3** (en kötü gün %0 → %40) |
| en iyi %1 (günde ~5) | %67,7 | %78,5 |

Kasa (en iyi %2, 30 sn, iz, her hafta $1000'dan): 20 kriter masraflı 2,58x / 4,96x / 1,66x; + holder 1,83x / 4,59x /
1,69x (brüt 3,28/5,99/1,95 ↔ 3,40/5,59/1,96). → **Holder kriterleri 2x isabetini ~11 puan artırıyor ama haftalık kasa
sonucunu artırmıyor** (ilk haftada masraflı daha kötü). Uyarı: aynı test günlerinde bir karşılaştırma daha (çoklu
deneme). Canlıda her aday için lansmandan itibaren Transfer logları gerekir (RPC yükü, bildirimde birkaç sn gecikme).
Kullanıcı kararı (3 Ekim): kâğıt teste ikinci model olarak eklendi (§3). "Fomo holder payı" kriteri çıkarıldı:
ileride Fomo'ya gelen cüzdanları da sayıyordu (gelecek bilgisi) ve bot bütün Fomo cüzdan geçmişini bilmiyor; 8 kriterle
sonuç aynı (en iyi %2: 2x %74,5; haftalık masraflı 1,83x / 4,31x / 1,49x). Araştırma formülleri canlıyla eşitlendi
(anın kendi bloğu, 10 dk = 5.958 blok, arz yoksa sadece o ana kadarki mint'ler, sniper o ana kadar).

## 5. Denenip bırakılanlar (neden)

| Deneme | Sonuç |
|---|---|
| "Bot alır, 1 saat tutar" + 915 çıkış stratejisi, $ kâr/kayma hesapları (1–2 Ekim) | Hedef dışı: satış kararı kullanıcının. Silindi (`exit_search`, `scan_trade`, `scan_export`, `rise_build`). |
| DexScreener 5-30 dk örnekleriyle ölçüm | Zincir fiyatlarına göre 2-3 kat iyimser → silindi |
| Momentum v1/v2, rug riski, ÇIK/DİKKAT | Zincir verisiyle kanıtlanmadı → silindi (momentum yerine 2. adımda 2x ihtimali gelecek) |
| Mezuniyet öncesi Pons takibi, zincirde çok erken an (curve) | İsabet artmıyor → silindi (`curve_*`) |
| Cüzdan kopyalama | Cüzdan başarısı kalıcı değil (korelasyon ~0,1) |
| GoPlus | Pons coinleri aynı şablon; geçmiş testine yaramıyor (canlıda ek kontrol olabilir, 1. adımda bakılır) |
| Geliştirici geçmişi (yükseliş için) | Geliştiricilerin %88'i tek coin çıkarıyor; ayırmıyor (güvenlik için 1. adımda bakılır) |
| İşlem günlüğü (`/aldim`, `/sattim`) | Kullanıcı istemedi, geri alındı |
| X/Twitter sosyal sinyaller | Ücretli → yok |

## 6. Ölçüm kuralları (her biri bir kez sahte sonuç üretti)

1. **Gelecek bilgisi yok:** Kriter sadece bildirim anına kadarki veriden hesaplanır.
2. **Bildirim fiyatı o anda bilinen son fiyattır** (son alım). Gelecekteki bir işleme bağlanmaz ("sonraki alımın
   fiyatı" değil). Son 3 alımın ortancası da olmaz: yükselen coinde son fiyatın gerisinde kalır ve 2x'i şişirir
   (2 Ekim: %28,5 → gerçek %25,9; hızlı yükselenlerde %36 → %31).
3. **Evren seçimi yok:** "İleride Fomo'ya gelen / en az N alım daha gelen coinler" gibi bir seçim gelecek bilgisidir.
   O anda bilinen bütün coinler sayılır.
4. **2x iki ardışık alımla tutulmalı.** Fomo toplu işlemlerinde ~%5 satış fiyatı bozuk; tek basım 2x sayılmaz. Coin
   başına tavan 100x.
5. **Düşüş ve son değer tüm işlemlerden okunur** (sadece alımlardan değil). Ölü coin (6 saat işlem yok) yarı fiyat.
6. **Yol sırası korunur:** iki olaylı kurallarda hangisi önce olduysa o geçerli.
7. **Süresiz 2x, veri sonuna dikkat:** veri bitmeden önce yeterince izlenmemiş coin "2x olmadı" sayılmaz; ya
   yeterli izleme süresi olanlar sayılır ya da "henüz bilinmiyor" ayrı gösterilir.
8. **Doğrulama:** kriter görmediği günlerde sınanır (kayan pencere); gün gün sonuç ve hata payı; "en iyi %1 hariç"
   şans kontrolü. Sonuç fazla iyiyse önce hata aranır.
9. **Başarı brüttür** (kullanıcı kararı). Komisyon/kayma sadece 3. adımda "girseydik sonuç ne olurdu" için, kullanıcıyla
   birlikte kararlaştırılırsa.
10. **Eksik veri de bilgi taşır.** Bir özelliğin dolu ya da boş olması gelecekteki bir koşula bağlı olmamalı. Örnek
   (2 Ekim): arz sadece "toplam 20+ işlem gören" coinler için çekilmişti → FDV'nin boş olması "bu coin ölecek"
   demekti, modele gelecek sızıyordu. Arz artık 3 alıcıya ulaşan her coin için çekiliyor.

## 7. Veri ve araçlar

**Arşiv:** GitHub `veri` dalı, günlük parquet (1 Eylül'den bugüne aralıksız; 3-17 Eylül boşluğu 2 Ekim'de dolduruldu). Pump.fun: `solana/`, BNB: `bnb/` (sunucudan her gece).
Yeni oturumda araştırma veritabanını kurmak:
```
git fetch origin veri && git worktree add /tmp/veri origin/veri
python scripts/data_import.py /tmp/veri fomo.db
python scripts/fomo_supply.py fomo.db
python scripts/pons_launches.py fomo.db
```
Yeni günler: `fomo_download.py <gün> yeni.db` → `data_merge.py yeni.db fomo.db` → `data_export.py fomo.db /tmp/veri`
→ veri dalına commit/push. Araştırma venv'i: `numpy pandas pyarrow scikit-learn`.

**Robinhood yeni günler (3 Ekim'den, §0 D8):** bot gördüğü her Fomo işlemini `rhscanner.db` `fomo_log`'a yazar; gece
gönderimi `robinhood/<gün>/trades.csv.gz` (3 günden eskisi botun DB'sinden silinir). Araştırmada:
`python scripts/solana_import.py /tmp/veri fomo.db --chain robinhood` (sadece son bloktan sonrası; parquet arşivle bot
günleri arasında boşluk varsa `retrain.py` zincirden indirir).
**Haftalık yeniden eğitim:** `python scripts/retrain.py <çalışma klasörü>` → veri, 5. alıcı anları, holder özellikleri,
iki model (`paper_model.json`, `paper_model_h.json`; JSON = sklearn ve canlı kriter = araştırma kontrolleriyle). Sonra
testler, `fresh_test.py` ile son günler, commit/push, kullanıcıya sunucu güncellemesi. Kâğıt test yeniden başlatmada
kaybolmaz ama karne model değiştiği andan sonrası için ayrı okunmalı (`/karne <saat>`).

**Betikler (`scripts/`):**

| Tür | Betik | Ne yapar |
|---|---|---|
| Veri | `fomo_download.py` | Zincirden bütün Fomo işlemleri (günde ~300k) |
| Veri | `data_merge.py` | Yeni indirilen işlemleri ana veritabanına ekler |
| Veri | `data_export.py` / `data_import.py` | `veri` dalı arşivi |
| Veri | `fomo_supply.py` | Coin arzları (FDV için) |
| Veri | `pons_launches.py` | Bütün Pons lansmanları (token, curve, geliştirici) |
| Veri (pump.fun) | `solana_import.py` | `veri` dalındaki `solana/` günlerini araştırma veritabanına yükler (toplayıcı: `rhscanner/solana.py`, gece gönderim: `rhscanner/solana_export.py`) |
| Veri | `transfer_download.py` | Coinlerin ilk saat token transferleri (holder özellikleri) |
| Araştırma (2. adımın temeli) | `winner_study.py` | Fomo 3./5./10./20. alıcı anları + özellikler + sonraki zirve |
| Araştırma | `transfer_features.py` | Bu anlara holder özellikleri ekler (`<k>` seçilebilir; anın kendi bloğu; 1 saatten geç anlar boş) |
| Araştırma (§0 A1) | `holder_study.py` | Holder kriterleri modele katkı sağlıyor mu: aynı walk-forward, 2x oranı + kasa simülasyonu |
| Eğitim (§0 D8) | `retrain.py` | Haftalık: arşiv + bot günleri → anlar → holder özellikleri → iki modelin dışa aktarımı |
| Araştırma (3. adım) | `exit_study.py` | Çıkış kuralları / seçim / tutar ızgarası, hafta hafta masraflı; final sınavı günleri ayrık |
| Araştırma (pump.fun, A8) | `pump_study.py` | pump.fun yeni coinlerinin 3./5./10. Fomo alıcısı anları, kriterler, 2x / tuzak / mezuniyet |
| Test (§0 A2) | `fresh_test.py` | Kâğıt test modeli görmediği günlerde (bot gibi seçim, 2x oranı, kasa simülasyonu) |
| Araştırma | `rise_detect.py` | "Ciddi yükseleni ayırabiliyor muyuz" raporu |
| Araştırma (1. adım) | `sell_probe_study.py` | V4 satış simülasyonu: bildirim anında ve 1/6/24 saat sonra satılabiliyor mu |
| Araştırma (3. adım) | `wave_study.py` | İkinci dalga anları (1 saatlik coin, 30 dk sessizlikten sonra 5 dk'da 5+ alıcı) |
| Araştırma (3. adım) | `profit_study.py` | Modeli işlemin net getirisiyle eğitir; 2x / kâr>0 / getiri modelleri hafta hafta |
| Simülasyon (3. adım) | `trade_sim.py` | Kullanıcının kurallarıyla işlem simülasyonu: gecikme, masraf, şans kontrolü, hafta hafta |
| Araştırma (2. adım) | `rise_study.py` | Bildirim anları, kriterler tek tek (eğitim/test), hepsi birlikte günlük yeniden eğitilen model |
| Kontrat | `compile_contracts.mjs` | `contracts/` derlemesi (solc 0.8.26, viaIR) |
| Araştırma (1. adım) | `trust_export.py` | Güven puanı modelini eğitir → `rhscanner/trust_model.json` |
| Araştırma (1. adım) | `security_study.py` | Güvenlik kontrolleri ↔ tuzak (rug/satılamayan) ve 2x; `report` modu tabloyu basar |

**Git dalları:**

| Dal | Ne |
|---|---|
| `claude/fomo-coin-scanner-app-mhz9rk` | **Asıl proje dalı.** Sunucu buradan kurulur. |
| `ccr-...` / `claude/...` | Oturum dalları; her değişiklik bunlara ve asıl dala birlikte gönderilir. Silinmiyorlar (kullanıcı kararı). |
| `veri` | Araştırma verisinin arşivi (günlük parquet). |
| `main` | GitHub'ın boş ilk dalı, kullanılmıyor. |
