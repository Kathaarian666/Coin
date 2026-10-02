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

Değişmeyen eski kararlar: sadece ücretsiz kaynaklar (X/Twitter API yok), Fomo "thesis" yazıları kullanılmaz.

**Neden yeniden hizalandı:** 24–27 Eylül'deki bot bu hedefe yakındı (güven + momentum puanı, bildirim). Sonra
DexScreener ölçümleri sahte sonuç üretti, bot sadeleştirildi ve araştırma "botun kendisi alıp 1 saat tutsa kaç $
kazanır" sorusuna kaydı (çıkış stratejileri, kayma, $ kâr). Kullanıcı satışa botun karışmasını istemiyor; o işler
bırakıldı.

## 2. Plan (her adımın sonunda durup kullanıcıyla bakılır; onaysız sonraki adıma geçilmez)

| Adım | Ne | Durum |
|---|---|---|
| **0** | Temizlik + bu belge + veri arşivini güncelleme | **bu adım** |
| **1** | **Güvenlik kriterleri (birlikte).** Her kontrol için: ne kontrol ediyor, neyi eliyor, geçmiş veride kaç coini eledi, elenenler gerçekten kötü müydü. Ekle/çıkar; hangisi **eler**, hangisi raporda **yazar**. | **sürüyor**: kararlar §1'de; sırada ölçüm |
| **2** | **Yükseliş kriterleri (backtest ile, birlikte).** Aday kriterler tek tek: 2x oranını ne kadar artırıyor, görmediği günlerde tutuyor mu. Bildirim anı karşılaştırması (Fomo'da 3./5./10. alıcı). Kriter listesi + model. | bekliyor |
| **3** | **Simülasyon (karar kapısı).** Güvenlik elemesi + model uçtan uca geçmiş veride: günde kaç bildirim, kaçı 2x, girseydik sonuç ne olurdu. "Yeterince kâr" tanımı ve 2x olmayanların nasıl sayılacağı bu adımda birlikte belirlenir. Yetmezse 1/2'ye dönülür. | bekliyor |
| **4** | **Bot.** Bildirim (güven + 2x ihtimali + nedenler), "2x oldu" haberi, karne. Kriterler kesinleşmeden bota dokunulmaz. | bekliyor |
| **5** | **Canlı izleme.** Karne (bildirimlerin kaçı 2x yaptı) simülasyonla karşılaştırılır. | bekliyor |

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
2. **Bildirim fiyatı o anda bilinen fiyattır.** Gelecekteki bir işleme bağlanmaz ("sonraki alımın fiyatı" değil).
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

**Git dalları:**

| Dal | Ne |
|---|---|
| `claude/fomo-coin-scanner-app-mhz9rk` | **Asıl proje dalı.** Sunucu buradan kurulur. |
| `ccr-...` / `claude/...` | Oturum dalları; her değişiklik bunlara ve asıl dala birlikte gönderilir. Silinmiyorlar (kullanıcı kararı). |
| `veri` | Araştırma verisinin arşivi (günlük parquet). |
| `main` | GitHub'ın boş ilk dalı, kullanılmıyor. |
