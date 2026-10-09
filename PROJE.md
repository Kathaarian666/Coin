# Fomo Coin Tarayıcı — Proje Belgesi

Son güncelleme: 3 Ekim (genel denetim, §0 D-maddeleri). Bu belge projenin tek özetidir: ne yapmak istiyoruz, plan, nerede
duruyoruz, ne biliyoruz, neyi bıraktık. Eski ayrıntılar ve silinen betikler git geçmişinde.

## 0. Açık işler (kullanıcı kuralı, 3 Ekim: hiçbir iş atlanmaz)

Kural: konuşulan bir iş bitmeden yeni işe geçilmez. Kullanıcı "şimdilik geç" derse iş burada **ertelendi** olarak
kalır ve her adım sonunda / uygun anda kullanıcıya hatırlatılır. Yeni oturumda önce bu listeye bakılır; iş bitince
satırı silinir (sonucu ilgili bölüme yazılır).

| # | İş | Durum |
|---|---|---|
| A2 | Taze gün testi: yapıldı (§4.6, 2x %80, 11 seçim); 7 Ekim'de 1-6 Ekim ile tekrarlandı (26 seçim, 2x %71, §4.4c); arşiv 6 Ekim sonuna kadar araştırma DB'sinde. Her gün yeni günler eklenip tekrarlanacak (kâğıt testle birlikte) | sürekli |
| A4 | Kâğıt test değerlendirmesi yapıldı (9 Ekim, §4.7): karne 3-8 Ekim ana model 19 seçim 1,02x (şimdiki kural, iyimser) / 5x kuralı 1,06x; holder modeli 1,14x / 1,13x; aynı günlerin final sınavı (gerçek çıkış) 5x 1,20-1,27x, şimdiki kural 0,86-0,91x. **Kararlar (kullanıcı, 9 Ekim):** 1 satış kuralı 5x → B1 · 2 `/canli` **açılmıyor** ("henüz istediğimiz seviyede değiliz") · 3 model: kârlı olan hangisiyse → B2 · 4 seçim payı %5 ölçülsün → B3 · 5 hedef tutmadı → iyileştirme çalışmaları (B4) · 6 yeniden eğitim → D8 · 7 pump.fun: kâr hedefli model (A8) | kararlar alındı |
| B1 | Satış kuralı 5x (kullanıcı "evet", 9 Ekim): **yapıldı** — `/canli` takibi "2x oldu" yerine 5x'te "🎯 5x oldu, şimdi hepsini sat" (`bot.watch_target`), 3 saatte "⏱ 3 saat doldu, kalanı sat" (`live_step`), takip penceresi 6 saat (`live.LIVE_WINDOW`); bildirimde "5x satış hedefi"; `/karne`'de 5x kuralı ana kural, eski kural karşılaştırma için | yapıldı, sunucuda (9 Ekim) |
| B2 | Model seçimi ("kârlı olan hangi modelse o", 9 Ekim): final sınavı 1-8 Ekim, gerçek çıkış değeri, 5x kuralı (1-7 Ekim haftası): **ana model 1,57x** (33 seçim, 2x %67) ↔ holder modeli 1,25x (31 seçim, 2x %62; 23 seçim ortak); şimdiki kuralla ikisi de ~0,85x. Kâğıt testteki holder önü (1,13x ↔ 1,06x) küçük örnek + iyimser değerleme → **ana model** (gerçek bildirim de onunla); holder kâğıt testte sürüyor, her yeniden eğitimde tekrar bakılır | yapıldı: ana model |
| B3 | Seçim payı ölçüldü (9 Ekim, §4.7): 5x kuralı, gerçek çıkış, kasanın %4/%2/%1'i. **Araştırma 10-30 Eyl** (walk-forward): %2 3,15x/hafta · %3 3,30x · %5 3,12x (en kötü hafta 1,75 → 1,78 → **2,34**). **Taze 1-8 Eki** (geçen haftanın modeli): %2 1,29x · %3 1,47x · **%5 1,72x** (86 seçim, günde ~11; en iyi işlem hariç 1,54x). %5'te likiditesi çekilen pay daha az (taze %16-19 ↔ en iyi %2'de %33). Şimdiki kural her payda zararda. → Küçülen pazarda %5 daha iyi, araştırmada eşit ama daha kararlı. **Kullanıcı "ok" (9 Ekim): seçim payı %5** (`paper.TOP = 0.05`; kâğıt test ve gerçek bildirim; tutar sıraya göre üçte birlerle %4/%2/%1; bildirimdeki 2x ihtimali en iyi %5'in walk-forward oranı: ana 0,51, holder 0,628) | yapıldı, sunucuda (9 Ekim) |
| B4 | Hedef (haftada kasa 2x) tutmadı (gerçek değerle ~1,2-1,7x) → **iyileştirme çalışmaları** (kullanıcı, 9 Ekim); `/canli` hedefe yaklaşınca yeniden konuşulacak. **1. Rug ayırma (9 Ekim, §4.8): elemek zararlı** — riskli seçimler (hook yok / launchpad dışı sahip) 5x kuralının asıl kazananları (işlem başı ~2,6x ↔ normal ~1,3x); elenince araştırmada kasa 3,1x → 1,6-1,8x. Hepsi sonunda çekiliyor ama 5x → çekilme ortanca ~14 dk (26'nın 3'ü 1 dk içinde) → hızlı satış şart. Sıradaki: bulguyu Ekim günleriyle doğrulamak (güvenlik bayrakları 2 Ekim'de bitiyor → yeni günler için çıkarılmalı), sonra bildirimde "riskli: 5x'te hemen sat" uyarısı / tutar — kullanıcıyla | sürüyor |
| A8 | Pump.fun araştırması (Robinhood'daki adımlar: güvenlik, yükseliş kriterleri, simülasyon, kâğıt test). 4 Ekim: ön çalışma (§4.5c). 8 Ekim: 4,7 günle ilk walk-forward model (§4.5d): en iyi %2'de 1 sa 2x %40 (Robinhood %54-60), günde ~25 seçim, mezuniyet çöküşü riski. Mezuniyet ayrımı: curve %90+ coinler hariç → en iyi %2'de 2x %47, tuzak %0 (§4.5d). 8 Ekim simülasyon: kârsız (5x kuralı 0,81x, 2x'te hepsi 0,85x; seçimler 2x yapıp 3 saatte 0,2'ye çöküyor, §4.5d). Kullanıcı kararı (8 Ekim, "ok"): 9-10 Ekim'de A4 ile birlikte yeni günlerle tekrar (`solana_import` → `pump_study` → `pump_rise --max-curve 90` → `pump_sim`); 9 Ekim: yeni günlerle de kârsız (0,69x); düşük hedef/kısa süre ve 3. alıcı da kârsız (§4.5d). Kullanıcı kararı (9 Ekim, "7 a"): son deneme kâr hedefli model → **o da kârsız** (5x kuralı 0,71x, §4.5d). **Kullanıcı kararı (9 Ekim): "pump.fun'u bekletelim, Robinhood'a odaklanalım"** — sunucu veri toplamaya devam eder; ileride daha çok veri ya da yeni fikirle dönülür | **ertelendi** (her adım sonunda hatırlatılacak) |
| A7 | BNB toplayıcı sunucuda çalışıyor (3 Ekim, `fombnb`: dakikada ~110-250 Fomo işlemi, 10-45 flap.sh lansmanı); Base bekletiliyor (kullanıcı onayı; geçmişi istendiğinde indirilir) | Base: ertelendi |
| A9 | `veri` dalı büyüyor (~120 MB/gün: pump.fun + BNB) → ~1 ay sonra GitHub'ın önerdiği sınıra (~5 GB) yaklaşır; daha sıkı biçim (adres sözlüğü, imza sütununu atma) ya da başka depolama gerekecek | **ertelendi** (kullanıcı, 4 Ekim: "acelesi yok, ileride"); ~1 Kasım'dan önce hatırlatılacak |
| D8 | Robinhood gece arşivi kuruldu; haftalık yeniden eğitim `scripts/retrain.py` (oturumda). **İlk eğitim 9 Ekim yapıldı**: 3 Eylül – 7 Ekim (22.052 an, 2x 7.178), iki model (`paper_model.json` 20 kriter, başlangıç eşiği 0,5317; `paper_model_h.json` 28 kriter), canlı kriter eşitliği tamam; sunucuda (9 Ekim akşamı, karne doğrulandı). Kâğıt testte eski model seçimleri ile yenileri karneyi karıştırır (karne alt satırı eğitim tarihini gösterir). **Haftalık Routine kuruldu** (kullanıcı "evet", 9 Ekim): her Perşembe 08:53 (İstanbul) bu oturuma, `trig_01Vd1J2yVyuye8obmrZqtzzV`; önce eski modellerin haftalık final sınavı (ana ↔ holder), sonra yeniden eğitim | yapıldı; ilk Routine 15 Ekim |
| K3 | `VERI_GITHUB_TOKEN` ~1 Ocak'ta dolar → yenileme hatırlatması (Aralık sonu) | Aralık |

## 1. Amaç (kullanıcı kararları, 2 Ekim)

Bot, Fomo uygulamasında (Robinhood Chain) **yeni çıkan coinler** arasından **yükselme ihtimali en yüksek olanları**
bulur, güvenlik taramasından geçemeyenleri sessizce eler, kalanları kullanıcıya rapor olarak gönderir.
**Alıp almama kararı kullanıcınındır.** İşlemler elle, Fomo'da yapılır; bot alım-satım yapmaz.

| Konu | Karar |
|---|---|
| Rapor | **Güven puanı** + **2x ihtimali** (model puanı ve detayı: puanı en çok etkileyen nedenler) + bildirim fiyatı |
| Başarı | Coin **bildirim anındaki fiyatın brüt 2x'ine** ulaşır. Süre önemsiz, üst sınır yok. Kayma ve komisyon başarı tanımına girmez. (Seçim ölçüsü; kâr satış kuralına bağlı: 9 Ekim'den beri 5x kuralı, aşağıda.) |
| Bildirimden sonra | **9 Ekim'den beri (kullanıcı "evet"): bot coin bildirim fiyatının 5x'ine ulaşınca "🎯 5x oldu, sat", 3 saatte ulaşmazsa "süre doldu, sat"** der (önce: "2x oldu"); likidite çekilirse **"⚠️ likidite çekiliyor"**. Satış kararı kullanıcının. |
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
- **5x kuralı (6 Ekim, §4.4c, kullanıcı "evet"):** aynı seçimlere (iki modelde de) ikinci bir sanal işlem: iki ardışık
  alım bildirim fiyatının 5 katına ulaşınca hepsi satılır; gelmezse 3 saat sonra son Fomo fiyatıyla satılır, ama o
  anda coinin en son V4 havuzunun net likiditesi zirvesinin %20'sinin altındaysa değer 0 (`bot.pool_pulled`; havuz yoksa
  — coin hâlâ lansman curve'ünde — Fomo fiyatı). Zarar-kes yok. `/karne`'de ayrı satır (5x yapan, 3 saatte satılan,
  likiditesi çekilmiş, sanal kasa), son seçimlerde her birinin 5x durumu. `/kagitbildirim ac` ise 5x anında "🎯 5 katına
  ulaştı, şimdi hepsi satılır" mesajı gelir (kuralın hız gerektirdiğini pratikte görmek için). Güncellemeden sonra son
  ~3 günün seçimleri de geriye dönük hesaplanır (eski 5x'ler için mesaj gitmez).
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

### 4.5d pump.fun yükseliş modeli, ilk walk-forward (8 Ekim, §0 A8, 2. adımın ilk denemesi)
Veri: `veri` dalı `solana/` 3 Ekim 07:09 – 7 Ekim (3,47 milyon Fomo işlemi; tek boşluk 7 Ekim 11:14, 8 dk).
`pump_study.py` → 27.947 yeni coin; 5. alıcıda ~1.280 an/gün (Robinhood'da şu an ~190). `scripts/pump_rise.py`:
her test günü (5/6/7 Ekim) önceki günlerle eğitilen model (botun ayarları, 20 kriter), seçim = günün en iyi %2 / %5'i.
Sadece en az h saat izlenmiş anlar (vurmuş/vurmamış fark etmez).

| 5. alıcı | 1 saatte 2x | 6 saatte 2x | 1 sa tuzak | mezun |
|---|---|---|---|---|
| hepsi | %24,1 | %25,8 | %4,0 | %25 |
| en iyi %5 (günde ~60) | %39,9 | %45,4 | %3,7-6,2 | %48-50 |
| **en iyi %2 (günde ~25)** | **%40,3** | **%39,4** | %6-7 | %47-50 |
| en iyi %1 | %44,4 | %27,3 | %6-9 | %49-53 |

- Model işe yarıyor (en iyi %2-5'te 2x oranı ~1,6-1,8 katı) ama **Robinhood'dan zayıf**: orada en iyi %2'de 1 saatte 2x
  %54-60, süresiz %64-71. → "En az Robinhood kadar iyi" hedefi henüz tutmuyor. Buna karşılık seçim sayısı ~7 katı
  (günde ~25), kasa büyümesi seçim sayısına bağlı (§0 A4).
- En etkili kriter **piyasa değeri** (sonra curve doluluğu, geliştiricinin önceki coinleri, son 60 sn alım payı). Model
  mezuniyete yakın coinleri seçiyor (seçimlerin ~%50'si mezun oluyor, hepsinde %25) — 7 Ekim'de en iyi %2'de tuzak
  %18-25 (mezuniyet çöküşü, §4.5c). Tuzak/mezuniyet riski ayrıca ele alınmalı.
- Sınırlar: 3 test günü, ~70 seçim; ilk test günü 2 günlük veriyle eğitildi. Günler eklendikçe tekrarlanacak.
- **Mezuniyet ayrımı (8 Ekim, kullanıcı "1 ile başla"):** tuzakların %85'i mezun olan coinlerde; 5. alıcı anındaki
  curve doluluğuna göre (hepsi): %70-80 → 1 sa 2x %34 / tuzak %0; %80-90 → %33 / %2; **%90+ → %31 / %36**. Aynı eşik
  sadece ilk iki günde de görülüyor (%85-90 tuzak %6, %90-95 %19, %95+ %59) → sonradan uydurulmuş değil.
  `pump_rise.py --max-curve 90` (doluluğu %90'ı aşan coinler eğitimden ve seçimden çıkar; bilinmeyen kalır), 1 sa 2x
  hedefli model, walk-forward: **en iyi %2 → 2x %46,9, tuzak %0** (önce %40,3 / %6,9), gün gün %45-48 (kararlı),
  günde ~21 seçim; en iyi %5 → %40,1. %85 eşiği daha kötü (%40,0). 6 saat hedefli model daha zayıf (en iyi %2 %33,9;
  1 saat hedefli modelin seçimleri zaten 6 saatte de en az %47). → Robinhood'la fark daraldı (%47 ↔ %54-60) ama
  kapanmadı.
- **Simülasyon (8 Ekim, `scripts/pump_sim.py`, 3. adımın ilk denemesi):** aynı seçimler (en iyi %2, 5-7 Ekim, 3 saat
  izlenmiş 62 seçim), Robinhood'daki işlem: 30 sn geç, Fomo komisyonu (en az $0,95) + pump.fun ücreti %1,25 + kayma,
  kasanın %4/%2/%1'i. **Çıkış değeri burada zincir gerçeği:** her curve olayı curve'ün işlem sonrası rezervlerini
  taşıyor (Fomo dışı işlemler dahil) ve curve'den likidite çekilemez (PumpSwap'ta kayıtlı rezervler işlem fiyatlarının
  ~%10 altında, iki yönde de → orada işlemin kendi fiyatı). 3. saatte elde kalanların son Fomo işlemi medyan 91 dk
  önce; sonraki işlem fiyatı medyan aynı (0,98) → "temkinli" değer farkı küçük.
  - Sonuç **kârsız**: 5x'te hepsi, 3 sa (Robinhood'da seçilen kural) **0,81x** (gün gün 0,73 / 0,99 / 1,14; 5x'e 62'nin
    10'u ulaştı, %16 — Robinhood'da %36); 2x'te hepsi, 1 sa 0,85x; 3x/10x hedefler 0,70-0,80x; Robinhood'un şimdiki
    kuralları 1,21x ama tek işlemin şansı (en iyisi hariç 0,75x).
  - Neden: seçimler hızlı yükselip hızlı çöküyor — 1 saatteki zirve medyan 2,0x, 3. saatte değer medyan alış
    fiyatının **0,20 katı**. İşlem başı ortalama ~1,06x (2x'te hepsi: 1,08x), masraf bunu siliyor; asgari komisyon
    olmasa bile 0,93-0,95x.
  - Sınırlar: 3 gün, 62 seçim; model 2-4 günle eğitildi; Fomo'nun Solana komisyonu bilinmiyor (Robinhood'unki varsayıldı).
- **Yeni günlerle tekrar (9 Ekim, 5,7 gün; test 5-8 Ekim):** en iyi %2'de 1 sa 2x %36,9 (8 Ekim %10,5'e düştü), tuzak %0,
  günde ~21 seçim. Simülasyon (81 seçim) yine **kârsız**: 5x kuralı **0,69x**, 2x'te hepsi 1 sa 0,58x, Robinhood'un
  şimdiki kuralları 0,94x (en iyi işlem hariç 0,57x). En iyi %5 (195 seçim) daha kötü (0,13-0,49x).
  - **Alternatifler (anlaşıldığı gibi):** düşük hedef + kısa süre (1,3x / 1,5x / 2x, 10 dk – 1 sa): 0,59-0,67x;
    işlem başı ortalama 0,84-0,92x, yani **pump.fun ücreti dahil brüt bile zararda** (yükselen çok ama düşenler sert
    düşüyor). **3. alıcı anı** daha kötü (111 seçim, 0,19-0,52x). Kalan deneme: kâr hedefli model.
  - **Kâr hedefli model (9 Ekim, kullanıcı "7 a", `scripts/pump_profit.py`):** her 5. alıcı anının (5.963, curve ≤ %90)
    üç satış kuralıyla işlem sonucu (Fomo komisyonu öncesi; ortalama 0,78-0,81x — anların çoğu zararla biter), model
    2x yerine bu sonuca göre eğitildi (regresyon, walk-forward). En iyi %2 (82 seçim, 5-8 Ekim): 5x kuralı **0,71x**
    (2x modeli 0,67x), 2x'te hepsi 1 sa 0,74x (0,57x), 1,5x 1 sa 0,60x (0,65x); tahmin ↔ gerçek sıra korelasyonu
    0,10-0,20. → Biraz daha iyi seçiyor ama **hâlâ kârsız**. pump.fun'da 5. Fomo alıcısı anındaki Fomo akışı + fiyat
    kriterleriyle (30 sn gecikme, Robinhood'daki masraf varsayımıyla) kâr edilemiyor.

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

### 4.4c Gerçek çıkış değeriyle kural taraması (4 Ekim, §0 A10)
`scripts/exit_truth.py`: en iyi %2'lik 222 seçimin (10 Eylül – 1 Ekim) çıkış anlarında (1/3/6/24 sa) zincirdeki gerçek
fiyat (Pons curve + coinin bütün V4 havuzlarındaki işlemler). Likidite çekilmesi için şu kural kullanıldı: havuzun net
likiditesi bir blok sonunda zirvesinin %20'sinin altına iner ve bu, Fomo'nun işlem yaptığı havuzda son işlemden sonra
olur. Sonuç: gerçek / son Fomo fiyatı ortancası 1,00, ama seçimlerin **~%20'sinde (45) likidite çekilmiş** →
değer 0. Ölçülemeyen %3-6 (coin başka havuza geçmiş); iki yönde de değerlendi (0 / Fomo fiyatı), sonucu değiştirmiyor.
`scripts/exit_truth_rules.py` (aynı simülasyon: masraflı, 30 sn, haftalık $1.000; 3 hafta, 10-30 Eylül):
- **Şimdiki kurallar** (2x'te yarı, %50 zarar-kes, zirveden %50) gerçek değerle haftada **0,80-1,17x** (süre sınırına
  göre) → kârsız. Olağan değerlemenin en iyisi (5x'te yarı, 1 sa) 9,9x değil **2,0x**.
- **En iyi: 5x'e ulaşınca hepsini sat** (zarar-kes yok, kalan 1-24 sa sonra satılır; süre neredeyse fark etmiyor):
  haftada **~3,15x** (2,85 / 6,27 / 1,76; en kötü hafta 1,76x; en iyi %1 hariç 3,0x). Komşu kurallar da aynı bölgede
  (en iyi 8'in hepsi "5x'te hepsi").
- **Tuzak eleme denemeleri kötüleştirdi:** sadece Pons coinleri → 1,30x (büyük kazananların yarısı Pons dışı);
  güven puanı ≥ 50 (her gün önceki günlerle eğitilen) → 2,25x. 5x'te hemen satınca rug'lar çoğunlukla sonra geliyor.
- **Hata arandı** (`scripts/exit_truth_delay.py`): 221 seçimin 79'u 3 saat içinde 5x'e ulaşmış, ortanca **9,6 dk**
  sonra. Zincirde ölçülebilen 50'sinin hepsinde zincirdeki fiyat da 5x civarı (ortanca 5,4x, en düşük 3,4x) → veri
  hatası değil. **Satış gecikmesi:** 1 dk geç → 3,55x, 5 dk → 6,1x (yükseliş sürüyor), **15 dk → 79'un 17'sinde
  likidite çekilmiş** (4,3x). → Kural ancak bildirim anında ve hızlı uygulanırsa işe yarar; "5x oldu" haberi anında
  gelmeli ve satış birkaç dakika içinde yapılmalı.
- Sınırlar: sadece 3 hafta; kural aynı haftalarda seçildi (ızgarada 120 kural); 1 Ekim+ final sınavı için yalnız 1
  seçim var → asıl sınav yeni günler ve kâğıt test olacak.
- **Final sınavı (7 Ekim):** sunucudaki model (`paper_model.json`, 1 Ekim 11:18'e kadar eğitildi) hiç görmediği
  1 Ekim 11:31 – 6 Ekim günlerinde, bot gibi seçim (son 48 saatin en iyi %2'si; `fresh_test.py --picks`): 1.220 coin
  5. alıcıya ulaştı, **26 seçim, 2x %71** (17/24; araştırma %64). Gerçek çıkış değeri (`exit_truth.py`): seçimlerin
  **%35'inde likidite çekilmiş** (araştırmada %20). Aynı simülasyonla (~5,5 gün, tek "hafta"):
  **5x'te hepsini sat → 1,60x** (1 / 3 / 24 sa sınırı 1,59-1,60x; en iyi işlem hariç 1,39x); şimdiki kurallar
  (süre sınırıyla) 0,87-0,98x; 5x'te yarı 1,07x; sadece Pons 1,29x. → 3 haftada seçilen kural görülmemiş günlerde de
  en iyisi ve kârlı; haftalık oran araştırmadan düşük (seçim az: pazar küçüldü, §0 A4). Güven puanı filtresi
  sınanamadı (güvenlik verisi 2 Ekim'de bitiyor).
- **Final sınavı, yeni günlerle (9 Ekim):** 1-8 Ekim (model hâlâ görmedi), 1.540 coin, **33 seçim, 2x %67** (20/30),
  1 sa 2x %52; likiditesi çekilmiş %33. Gerçek çıkış değeriyle 1-7 Ekim haftası (8 Ekim 3 günden kısa, hafta sayılmadı):
  **5x'te hepsi → 1,58x** (1/3/24 sa sınırı 1,55-1,58x); şimdiki kurallar **0,82-0,85x**; sadece Pons + şimdiki
  kurallar ~1,0x. → Sonuç 7 Ekim'deki sınavla aynı: 5x kuralı görülmemiş günlerde de kârlı, şimdiki kurallar zararda.

### 4.7 Kâğıt test değerlendirmesi ve kararlar (9 Ekim, §0 A4)
Karne (3-8 Ekim, ~5,5 gün; model 1 Ekim'e kadarki veriyle eğitildi): ana model 1.038 coin puanladı, **19 seçim**, 2x yapan
9, zarar-kes 9; şimdiki kural kasa **1,02x** (açık/kalan pay son Fomo fiyatıyla → iyimser), 5x kuralı **1,06x** (15
seçim, en eski 4'ünün işlem geçmişi silinmişti; 5x yapan 4, 3 saatte satılan 11, likiditesi çekilmiş 2). Holder modeli:
17 seçim, **1,14x** / 5x ile **1,13x** (5x yapan 5). Aynı dönemin final sınavı (bot gibi seçim, `exit_truth` gerçek çıkış,
22 seçim): 5x kuralı 1,20-1,27x, şimdiki kurallar 0,86-0,91x → karne sınavla tutarlı; şimdiki kural gerçekte zararda.
Seçim günde ~3,5 (pazar küçülüyor, §0 A4 eski notu: bot işlem kaçırmıyor). Hedef (haftada kasa 2x) tutmadı.
**Kullanıcı kararları:** 1 satış kuralı 5x (B1) · 2 `/canli` açılmıyor ("henüz istediğimiz seviyede değiliz") · 3 model:
"kârlı olan hangi modelse o" (B2) · 4 seçim payı %5 ölçülsün (B3) · 5 iyileştirme çalışmaları (B4) · 6 yeniden eğitim
(D8) · 7 pump.fun'da kâr hedefli model (A8).

**Seçim payı (9 Ekim, §0 B3):** `exit_truth.py` araştırmanın en iyi %5'ine (553 seçim) ve geçen haftanın modeliyle taze
1-8 Ekim'in en iyi %5'ine (86 seçim, bot gibi 48 saatlik eşik) genişletildi; `exit_truth_rules.py` %1/%2/%3/%5.
5x kuralı (3 sa, kasanın %4/%2/%1'i): araştırma %2 3,15x · %3 3,30x · %5 3,12x (en kötü hafta 1,75 / 1,78 / 2,34);
taze %2 1,29x · %3 1,47x · %5 1,72x. Dikkat: tazede "%2" burada %5'lik seçimlerin puanca üst %40'ı; bot gibi %2 eşiğiyle
aynı model 1,57x vermişti (33 seçim) → bu büyüklükte örneklerde fark gürültü düzeyinde, ama yön aynı: pay büyüdükçe
kasa en az aynı kalıyor, en kötü hafta iyileşiyor; en üstteki seçimlerde rug payı daha yüksek (%33 ↔ %16).

### 4.8 Riskli seçimler ve 5x kuralı (9 Ekim, §0 B4)
Araştırmanın en iyi %5'i (553 seçim, 10-30 Eylül; güvenlik verisi 18 Eylül'den, 303 seçimde): Pons coinlerinde rug **%0**
(372), Pons dışı %28; havuzunda hook olmayan 49 seçimde rug %65 (2x %69), launchpad dışı sahibi olan 36'da rug %83
(2x %81). Bu riskli seçimleri elemek (`exit_truth_rules.py` filtreler `sahipsiz` / `hookvar` / `ikisi`) 5x kuralında
kasayı düşürüyor: en iyi %5'te 3,12x → 1,65-1,77x/hafta (17-23 Eylül haftası 4,56x → ~0,9x); sadece Pons 1,19x.
`scripts/risky_picks.py`: riskli 50 seçimin 26'sı 3 saatte 5x yapıyor (ortanca 9 dk; normal 253'ün 47'si, 14 dk),
45'inde likidite çekiliyor (ortanca 17 dk). İşlem başı (5x ya da süre dolunca): riskli **~2,6-2,7x** (5 dk – 3 sa
arası neredeyse aynı; erken çıkış sıfırları 13 → 6'ya indirir ama 5x'leri de keser), normal ~1,2-1,3x (kısa süre
ortancayı yükseltir, ortalama aynı). 5x yapan 26 riskli coinin hepsinin likiditesi sonra çekiliyor; 5x anından
çekilmeye 0,5 – 59 dk (ortanca ~14 dk; 1 dk içinde 3, 5 dk içinde 5). → Kâr büyük ölçüde "pompala-çek" coinlerden
geliyor; 5x'te **hemen** satılırsa yakalanıyor. Sınır: 2 hafta, 50 riskli seçim; Ekim günleri için güvenlik bayrakları yok.

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
| Araştırma (A8) | `pump_rise.py` | pump.fun yükseliş modeli, walk-forward (gün gün), en iyi %1/2/5 |
| Araştırma (A8) | `pump_sim.py` | pump.fun seçimlerinin işlem simülasyonu, çıkış değeri curve rezervlerinden |
| Araştırma (A8) | `pump_profit.py` | pump.fun kâr hedefli model (kural sonucuna göre regresyon) ↔ 2x modeli |
| Araştırma (B4) | `risky_picks.py` | Riskli seçimler (hook yok / sahip var) 5x kuralında: süre seçenekleri, 5x → çekilme süresi |
| Araştırma (A10) | `exit_truth.py` | Seçimlerin çıkış anındaki gerçek fiyatı: curve + V4 havuzlarındaki bütün işlemler, net likidite çekilmesi |
| Araştırma (A10) | `exit_truth_rules.py` | Çıkış kuralı taraması, gerçek çıkış değeriyle; Pons / güven puanı filtreleri |
| Araştırma (A10) | `exit_truth_delay.py` | 5x kuralında satış gecikmesinin etkisi; Fomo 5x'inin zincirde doğrulanması |
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
