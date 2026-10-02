# Fomo Coin Tarayıcı — Proje Belgesi

Son güncelleme: 2 Ekim (1. adım: güvenlik kararları). Bu belge projenin tek özetidir: ne yapmak istiyoruz, plan, nerede
duruyoruz, ne biliyoruz, neyi bıraktık. Eski ayrıntılar ve silinen betikler git geçmişinde.

## 1. Amaç (kullanıcı kararları, 2 Ekim)

Bot, Fomo uygulamasında (Robinhood Chain) **yeni çıkan coinler** arasından **yükselme ihtimali en yüksek olanları**
bulur, güvenlik taramasından geçemeyenleri sessizce eler, kalanları kullanıcıya rapor olarak gönderir.
**Alıp almama kararı kullanıcınındır.** İşlemler elle, Fomo'da yapılır; bot alım-satım yapmaz.

| Konu | Karar |
|---|---|
| Rapor | **Güven puanı** + **2x ihtimali** (model puanı ve detayı: puanı en çok etkileyen nedenler) + bildirim fiyatı |
| Başarı | Coin **bildirim anındaki fiyatın brüt 2x'ine** ulaşır. Süre önemsiz, üst sınır yok. Kayma ve komisyon başarı tanımına girmez. |
| Bildirimden sonra | Bot sadece coin 2x'e ulaşınca **"2x oldu"** haberi verir. Kısmi/tam satış kararı kullanıcının. Başka bir şey yapmaz. |
| Bildirim sayısı | Mümkün olduğunca az. Eşik, backtest'in "günde kaç bildirim · yüzde kaçı 2x" tablosuna bakılarak birlikte seçilir. |
| Güvenlik — eleme | **Sadece satılamama elenir:** honeypot ya da toplam alım+satım vergisi **≥ %10**. Satılabilirlik doğrulanamazsa coin elenmez, raporda "⚠️ satılabilirlik doğrulanamadı" yazar. |
| Güvenlik — rapor | Diğer 14 kontrol **eleme yapmaz**, raporda tek tek görünür (bilinmeyen "bilinmiyor" yazar). Ayrıca 0-100 **güven puanı**; her kontrolün puana etkisi geçmiş veride tuzak oranını ne kadar artırdığına göre belirlenir. |
| Güvenlik — kaynak | Kendi zincir kontrollerimiz + GoPlus + GeckoTerminal + DexScreener (hepsi ücretsiz, Robinhood Chain'i destekliyor). Dış kaynaklar yeni coinlere geç yetişiyor (40 dk'lık coinlerin çoğunda honeypot "bilinmiyor") → asıl yük zincir kontrollerinde, dış kaynak ikinci görüş. |
| "Tuzak" tanımı | Güvenlik ölçümünde kötü coin = **satılamayan** (honeypot/yüksek vergi) ya da **rug** (likidite çekildi / fiyat kısa sürede %90+ çöktü, 2x görmeden). Normal sönen coin güvenlik değil, yükseliş konusu. |
| Kriterler | Model puanı kullanılabilir; kullanıcı puanın detayını görür. |
| Veri | Her kriter **gerçek Fomo zincir verisiyle** backtest edilir; DexScreener vb. tahmini veri karar ölçüsü olmaz. |

**Kapsam (2 Ekim):** şimdilik **sadece Robinhood Chain**. Fomo'da Solana (pump.fun), BNB, Base vb. zincirlerden de coin
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
| **0** | Temizlik + bu belge + veri arşivini güncelleme | **bu adım** |
| **1** | **Güvenlik kriterleri (birlikte).** Her kontrol için: ne kontrol ediyor, neyi eliyor, geçmiş veride kaç coini eledi, elenenler gerçekten kötü müydü. Ekle/çıkar; hangisi **eler**, hangisi raporda **yazar**. | bitti (2 Ekim): §1 kararlar, §4.1 ölçüm |
| **2** | **Yükseliş kriterleri (backtest ile, birlikte).** Aday kriterler tek tek: 2x oranını ne kadar artırıyor, görmediği günlerde tutuyor mu. Bildirim anı karşılaştırması (Fomo'da 3./5./10. alıcı). Kriter listesi + model. | **sürüyor**: ilk ölçüm §4.2 |
| **3** | **Simülasyon (karar kapısı).** Güvenlik elemesi + model uçtan uca geçmiş veride: günde kaç bildirim, kaçı 2x, girseydik sonuç ne olurdu. "Yeterince kâr" tanımı ve 2x olmayanların nasıl sayılacağı bu adımda birlikte belirlenir. Yetmezse 1/2'ye dönülür. | bekliyor |
| **4** | **Bot.** Bildirim (güven + 2x ihtimali + nedenler), "2x oldu" haberi, karne. Kriterler kesinleşmeden bota dokunulmaz. | bekliyor |
| **5** | **Canlı izleme.** Karne (bildirimlerin kaçı 2x yaptı) simülasyonla karşılaştırılır. | bekliyor |
| **6** | **Diğer zincirler** (Solana/pump.fun, BNB, Base…): Fomo'daki diğer zincirlere aynı yöntem; her zincir için ayrı veri ve güvenlik kontrolleri. | bekliyor (kullanıcıya her adım sonunda hatırlat) |

## 3. Şu anki durum

**Sunucudaki bot (`rhscanner/`, systemd servisi):** 4. adıma kadar olduğu gibi çalışıyor, değiştirilmeyecek.
- Fomo işlemlerini izliyor. Bir coin 10 dakikada yeterli alıcıya (`/minalici`) ve hacme (`/minhacim`) ulaşınca güven
  taraması yapıyor, skor `/minskor` üstündeyse Telegram'a rapor gönderiyor.
- Güven taraması: satılabilirlik, honeypot simülasyonu, kontrat, likidite, V4 hook, holder, geliştirici geçmişi,
  sniper/bundle, sahte hacim (Fomo churn). Ayrıntı: `README.md`. 1. adımda tek tek gözden geçirilecek.
- Eski "kayıt modu" (`scan.py`, `/kayit`): yeni coinleri 3. Fomo alıcısında puanlıyor, "1 saat tutsaydık" sonucunu
  kaydediyor, bildirim yok. Eski yaklaşım; 4. adımda yeni bildirimle değişecek.

## 4. Şimdiye kadar bilinenler (eski araştırma, 17–28 Eylül zincir verisi)

Bunlar yön gösterir; 2x tanımı (bildirim fiyatından, süresiz) ile 2. adımda **yeniden ölçülecek**.
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
- **Botta bulunan açık (4. adımda düzeltilecek):** `checks/contract.py` sadece 45 baytlık EIP-1167 klonu tanıyor;
  44 baytlık PUSH0 türü (714 coin, 33 asıl kontrat) tanınmıyor, kontrol klonun kendisine bakıyor.

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

## 7. Veri ve araçlar

**Arşiv:** GitHub `veri` dalı, günlük parquet (1-3 Eylül + 17 Eylül'den bugüne; 3-17 Eylül eksik, indirilmeyecek).
Yeni oturumda araştırma veritabanını kurmak:
```
git fetch origin veri && git worktree add /tmp/veri origin/veri
python scripts/data_import.py /tmp/veri fomo.db
python scripts/fomo_supply.py fomo.db
python scripts/pons_launches.py fomo.db
```
Yeni günler: `fomo_download.py <gün> yeni.db` → `data_merge.py yeni.db fomo.db` → `data_export.py fomo.db /tmp/veri`
→ veri dalına commit/push. Araştırma venv'i: `numpy pandas pyarrow scikit-learn`.

**Betikler (`scripts/`):**

| Tür | Betik | Ne yapar |
|---|---|---|
| Veri | `fomo_download.py` | Zincirden bütün Fomo işlemleri (günde ~300k) |
| Veri | `data_merge.py` | Yeni indirilen işlemleri ana veritabanına ekler |
| Veri | `data_export.py` / `data_import.py` | `veri` dalı arşivi |
| Veri | `fomo_supply.py` | Coin arzları (FDV için) |
| Veri | `pons_launches.py` | Bütün Pons lansmanları (token, curve, geliştirici) |
| Veri | `transfer_download.py` | Coinlerin ilk saat token transferleri (holder özellikleri) |
| Araştırma (2. adımın temeli) | `winner_study.py` | Fomo 3./5./10./20. alıcı anları + özellikler + sonraki zirve |
| Araştırma | `transfer_features.py` | Bu anlara holder özellikleri ekler |
| Araştırma | `rise_detect.py` | "Ciddi yükseleni ayırabiliyor muyuz" raporu |
| Araştırma (2. adım) | `rise_study.py` | Bildirim anları, kriterler tek tek (eğitim/test), hepsi birlikte günlük yeniden eğitilen model |
| Araştırma (1. adım) | `security_study.py` | Güvenlik kontrolleri ↔ tuzak (rug/satılamayan) ve 2x; `report` modu tabloyu basar |

**Git dalları:**

| Dal | Ne |
|---|---|
| `claude/fomo-coin-scanner-app-mhz9rk` | **Asıl proje dalı.** Sunucu buradan kurulur. |
| `ccr-...` / `claude/...` | Oturum dalları; her değişiklik bunlara ve asıl dala birlikte gönderilir. Silinmiyorlar (kullanıcı kararı). |
| `veri` | Araştırma verisinin arşivi (günlük parquet). |
| `main` | GitHub'ın boş ilk dalı, kullanılmıyor. |
