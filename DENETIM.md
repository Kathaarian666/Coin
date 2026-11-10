# Proje denetimi (10 Kasım 2026)

Kapsam: 24 Eylül'den bugüne bütün çalışma (248 commit, `PROJE.md`, haftalık sınavlar, sunucu durumu). Amaç: neyi yanlış
yaptık, neyi atladık, daha kârlı bir yola nasıl döneriz. Sayılar `PROJE.md`'deki ölçümlerden ve bugün yapılan iki kısa
kontrolden (§5) geliyor.

## 1. Kısa hüküm

- **Elimizde gerçek bir sinyal var ama gerçek para ile hiç sınanmadı.** Yedi haftadır bütün kâr rakamları simülasyon.
- **Sinyal küçük ve küçülüyor.** Görülmemiş beş haftada kasa haftada 1,57 → 1,92 → 1,37 → 0,91 → 1,31x (ortalama ~1,4x);
  bu, işlem başına $10-40 ile ve her hafta $1.000'dan yeniden başlayan bir hesap. Tutar büyüdükçe kâr eriyor (§2.2).
- **En büyük kayıp araştırmada değil, işletmede oldu:** bot 15 gün kör kaldı, kimse fark etmedi.
- **Hedef ("haftada kasayı 2x") gerçekçi değildi** ve bizi bir ay boyunca yan yollara (pump.fun, tüm-pazar) sürükledi.
- Önerilen yön: önce küçük parayla **gerçeklik testi**, sonra dürüst bir hedefle devam / bırak kararı; havuzu büyütmek
  için elimizde duran **BNB verisine** bakmak; işletmeyi alarm ile sağlamlaştırmak; projeyi sadeleştirmek (§6).

## 2. Yanlış gidenler (önem sırasıyla)

### 2.1 Hiç gerçek işlem yapılmadı
`/canli` hiç açılmadı ("henüz istediğimiz seviyede değiliz"). Sonuç: şu üç şeyi hâlâ bilmiyoruz ve hepsi kârı belirliyor:
- Bildirimden sonra gerçekte kaç saniyede alabiliyorsunuz (simülasyon 30 sn varsayıyor; 60 sn üstü zararlıydı).
- Fomo'nun gerçek komisyonu ve kayması (simülasyon: %0,5, en az $0,95, kayma tahmini — gerçek işlemle doğrulanmadı).
- Günün kaç bildirimine yetişebiliyorsunuz (bildirimler günün her saatinde geliyor; kazancın çoğu birkaç coinden).

Kâğıt test "seviyeye gelince açarız" diye bekletildi; ama seviye, ancak gerçek işlemle ölçülebilecek şeylere bağlı.

### 2.2 Hedef ve ölçü yanıltıcıydı
- "Haftada kasa 2x" bileşik olarak imkânsız bir hedef (yılda 2⁵²). Ölçümüz de bileşik değil: her hafta $1.000'dan başlıyor,
  işlem başına kasanın %1-4'ü ($10-40). Yani "1,31x" ≈ **o hafta ~$300 kâr**, katlanarak büyüyen bir şey değil.
- **Kapasite sınırı hiç hesaba katılmadı.** Seçilen coinlerin havuz derinliği ortanca ~$3.000 (dörtte biri $1.200'ün
  altında). Bugünkü hesap (§5): 5x yapan bir seçimde net çarpan $20-40 tutarda ~4,3-4,4x, $100'da 3,9x, $250'de 2,9x,
  $500'de 1,9x, $1.000'da zarar. → Strateji işlem başına ~$100-250'den fazlasını taşımıyor; **gerçekçi tavan haftada
  birkaç yüz dolar**, o da bildirimlere 7/24 yetişilirse.
- Bu tavan baştan konuşulsaydı "seviyeye gelmedi" diye beklemek yerine ya küçük parayla başlanır ya da proje daha erken
  yeniden yönlendirilirdi.

### 2.3 Pazar küçülürken aynı gölde kaldık
Fomo'da 5. alıcıya ulaşan yeni coin: Eylül 2. hafta günde ~1.000 → Eylül sonu ~310 → 5-11 Ekim ~150 → Ekim sonu ~60-70 →
Kasım başı 26-75. 3 saatte 5x yapanların oranı da %11 → %6. Araştırmanın Eylül sonucu (haftada ~3,1x) ile Ekim
sınavları (~1,4x) arasındaki farkın büyük kısmı bu. Model iyileştirmeleri bu düşüşü telafi edemez.

### 2.4 Kâr dar ve kırılgan bir kaynaktan geliyor
- Kazanç "riskli" (pompala-çek) coinlerden: son sınavlarda riskli seçim işlem başı 1,2-1,8x, normal seçim 0,44-1,07x
  (son hafta normal seçimler net zararda).
- Haftada 7-13 coin 5x yapıyor; sonuç bunlara bağlı. "En iyi işlem hariç" her hafta 0,15-0,3 düşüyor. Beş haftalık örnek
  bir kuralı ya da modeli ötekinden ayırmaya yetmiyor (ana ↔ holder, 15 dk kuralı, yan kural kararlarının hepsi gürültü
  düzeyinde farklara dayanıyor).

### 2.5 İşletme: kör uçuş
- **Bot 26 Ekim – 10 Kasım arası kördü** (Fomo kontrat değiştirdi). Sorun 3 gün sonra bulundu, düzeltme 29 Ekim'de
  hazırdı ama 12 gün kurulmadı. Kâğıt testin en değerli haftaları kayboldu.
- Solana gece gönderimi 27 Ekim'den beri bozuktu; 14 gün fark edilmedi.
- pump.fun günlük görevi 20 Ekim'den sonra hiç yeni sonuç üretmedi ama üç hafta her gün çalıştı (boşa kullanım);
  "17 Ekim'de kâr yoksa kapat" kuralı 24 gün gecikti.
- Kök neden: **botta alarm yok** ve otomatik görevlerin raporları sizin görmediğiniz oturumlara yazılıyor. Kararlar
  (ana/holder) dört hafta üst üste soruldu, cevapsız kaldı — soru size ulaşmadı ya da anlaşılır sorulmadı.

### 2.6 Canlı kâğıt test (planın 5. adımı) fiilen yürümedi
`/karne` en son 9 Ekim'de değerlendirildi. Haftalık "final sınavı" botun kendi canlı seçimleri değil, zincir verisiyle
araştırmanın tekrarı. 9 Ekim'de karne sınavdan düşüktü (1,06x ↔ 1,20-1,27x); botla araştırma arasındaki bu fark bir daha
ölçülmedi.

### 2.7 Dağılma
- pump.fun: 3 Ekim'de öncelik, 9 Ekim'de beklet, aynı akşam yeniden aç, 10 Kasım'da kapat. ~1 ay veri toplama, günlük
  görev, çok sayıda deneme → sonuç 1,00x.
- Tüm-pazar kriterleri (B5): yarım veriyle kapatıldı.
- Bu sırada **BNB verisi 3 Ekim'den beri toplanıyor ve hiç incelenmedi** (o gün Fomo'nun BNB işlem hızı Robinhood'un ~2
  katıydı). Base'in geçmişi ücretsiz indirilebiliyor, hiç indirilmedi.

### 2.8 Aşırı uyum ve aceleyle bota giren kurallar
- 3 Ekim gecesi onlarca varyant aynı 22 günde karşılaştırıldı (belgede uyarı var); Eylül rakamları iyimser çıktı.
- "Riskli seçimde 15 dk" kuralı iki haftalık veriyle bota kondu; sonraki dört sınavın ikisinde zararlı, birinde nötr.
  Raporlarda yazıldı ama karar alınmadı; kural hâlâ botta.

### 2.9 Ölçülmeden süren maliyetler
- Haftalık yeniden eğitimin fayda sağladığı hiç sınanmadı (dondurulmuş model ↔ yeniden eğitilen). Her hafta 1,5-2 saatlik
  oturum; en pahalı kısmı holder modelinin transfer indirmesi (~75 dk).
- Holder modeli beş haftada ana modele üstünlük göstermedi (kasa ~4,4 ↔ ~4,9), ama her hafta eğitiliyor ve soruluyor.

### 2.10 Belge ve iletişim
`PROJE.md` 1.040 satır; açık işler tablosundaki satırlar paragraflarca uzun. Yeni oturumlar için pahalı, sizin için
okunmaz. Kararlar çoğu zaman teknik dille soruldu ("ana ↔ holder").

### 2.11 Güvenlik notu
GitHub deposu **herkese açık**. İçinde sunucu IP'si, kullanıcı adı, bütün strateji ve veri var. Şifre/anahtar yok (token
sadece sunucuda), ama deponun gizli yapılması düşünülmeli (gizli olursa sunucunun güncelleme ve veri gönderimi için
token ayarı gerekir).

## 3. Doğru yapılanlar (korunmalı)
- Gelecek sızıntısı avı ve ölçüm kuralları (§6): sahte sonuçların çoğu yakalandı.
- Çıkış değerinin zincirdeki gerçek fiyattan ölçülmesi (likidite çekilmesi = 0): "şimdiki kural kârlı" yanılgısını bozdu.
- Görülmemiş günlerde haftalık sınav: Eylül iyimserliğini düzelten şey bu.
- Kanıt yokken `/canli`'yi büyük parayla açmamak; kârsız işleri (pump.fun, B5) sonunda kapatmak.

## 4. Atlananlar (özet)
1. Küçük parayla gerçek işlem testi. 2. Kapasite / dolar cinsinden hedef. 3. Bot alarmı. 4. BNB ve Base incelemesi.
5. Botun canlı seçimleri ↔ araştırma karşılaştırması. 6. Yeniden eğitimin ve holder modelinin fayda testi.
7. 15 dk kuralının yeniden kararı. 8. Sadece riskli seçimlerle işlem yapmanın sınanması (riskliyi elemek sınandı, tersi
sınanmadı).

## 5. Bugün yapılan iki kontrol
(Veri 3 Eylül – 12 Ekim, 22.570 an; walk-forward, 10 Eylül'den.)
- **Modeli doğrudan "3 saatte 5x" etiketiyle eğitmek işe yaramıyor:** en iyi %5'te 5x oranı 2x modeliyle %23 / %23
  (Eylül / Ekim), 5x modeliyle %25 / %22. Yani "yanlış hedefi öğretiyoruz" bir kaldıraç değil.
- **Kapasite:** §2.2'deki tablo. Not: derinlik bildirim öncesi Fomo işlemlerinin fiyat etkisinden tahmin (kaba); 5x anında
  havuz bir miktar daha derin olabilir, ama büyüklük sırası değişmez.

## 6. Önerilen yol

**Adım 1 — Gerçeklik testi (1-2 hafta, önce bu).** `/canli` açılır; sabit küçük tutarla (ör. $20-25) yetişebildiğiniz her
bildirimde işlem yaparsınız, satışta botun "5x oldu / süre doldu" mesajına uyarsınız. Cüzdanınızın **açık adresini**
(gizli anahtar değil) verirseniz gerçek alış/satışlarınızı zincirden okuyup simülasyonla yan yana koyarım: tepki süresi,
gerçek masraf, yetişilen bildirim oranı, gerçek kâr. Beklenen maliyet: en kötü durumda birkaç on dolar.

**Adım 2 — Dürüst hedef ve karar kapısı.** "Haftada 2x" yerine dolar hedefi (ör. "işlem başı $50 ile haftada net +$X").
Gerçeklik testi simülasyonun belirgin altındaysa ya da bildirimlere yetişmek pratik değilse Robinhood'da elle işlem
stratejisi bırakılır; tutuyorsa tutar kademeli artırılır (tavan ~$100-250/işlem).

**Adım 3 — Havuzu büyüt: BNB'ye ilk bakış.** Elimizdeki 3-26 Ekim BNB verisiyle (yeni indirme yok) Robinhood'daki ilk
sorular: günde kaç yeni coin 5. alıcıya ulaşıyor, 2x / 5x oranı, havuz derinliği. Robinhood'dan büyük ve derinse aynı
yöntem oraya taşınır; değilse BNB toplayıcı da kapatılır.

**Adım 4 — İşletme.** Bota alarm: 30 dk Fomo işlemi görmezse Telegram'a "⚠️ veri gelmiyor". Haftalık görevin raporu
kısa ve bildirimle (telefon / e-posta) size ulaşsın.

**Adım 5 — Sadeleştir.** Holder modelini kaldır (haftalık eğitim ~yarıya iner); 15 dk kuralına karar ver (öneri: kaldır,
herkes 3 saat); yeniden eğitimi iki haftada bire indir ya da dondurulmuş modelle bir kez karşılaştır; `PROJE.md`'yi
kısalt (güncel durum + kararlar öne, tarihçe arşive).

Sıra önerisi: 4 (yarım günlük iş, her şeyin sigortası) → 1 ile aynı anda 3 → 2 → 5.
