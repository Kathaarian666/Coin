# Proje notu (yeni sohbetler için — önce bunu oku)

Fomo uygulamasında (fomo.family) işlem gören Robinhood Chain coinlerini tarayan, güvenlik + momentum
analizi yapıp Telegram'dan bildirim gönderen bot. Kod: `rhscanner/`, ayrıntılı anlatım: `README.md`.

## Kullanıcı ve çalışma şekli
- Tüm iletişim **Türkçe**, adım adım. Kullanıcı çoğunlukla telefondan yazıyor.
- Sunucu komutlarını her birini ayrı kod bloğunda ver (telefondan kopyalanacak).
- **Şirket bilgisayarı kullanılmaz.** Her şey Oracle Cloud Shell + sunucu üzerinden.
- Telegram token, seed phrase, private key, Fomo girişi **asla sohbete yazdırılmaz**. Token sadece sunucudaki
  `.env` içinde (commit edilmez).
- Sadece ücretsiz kaynaklar. Ücretli bir şey (ör. Twitter API) önce fiyatıyla birlikte sorulur.
- Kullanım limiti önemli: gereksiz canlı test / uzun keşif yapma; bir iş beklenmedik uzarsa dur ve sor.
- Kullanıcıdan bulabileceğin bilgiyi isteme (ör. coin adresleri: GeckoTerminal/DexScreener aramasıyla bul).
- Branch: `claude/fomo-coin-scanner-app-mhz9rk` — sunucunun `install.sh`'ı bunu kurar. Oturum başka bir branch
  atarsa (ör. `claude/claude-md-durum-check-f88n39`) ikisine de push et (kullanıcı izin verdi), ikisi aynı kalsın.
  PR açma (kullanıcı istemedikçe).
- **Push'tan önce testler mutlaka geçmeli** (`python -m pytest -q`; komut zincirinde sonucu kontrol et).
- Telegram mesajları HTML: metinde çıplak `<` olursa Telegram mesajı reddeder ve komut sessizce cevapsız kalır
  → `escape()` / `&lt;` kullan; `tests/test_telegram_html.py` bütün rapor biçimlerini bu yüzden kontrol ediyor.

## Şu anki aşama (kullanıcı kararı, 1 Ekim — BAŞA DÖNÜŞ)
**Hedef:** yeni çıkan coinlerde (1) **güvenli** olanları ve (2) **koyduğumuz paranın en az 2x yapacağı** (1 dakikada da
olabilir, birkaç günde de) coinleri mümkün olduğunca baştan yakalamak. "3x / 5x / 60 dk" gibi sabit hedefler bırakıldı.
- **Güven** tarafı hazır sayılıyor, dokunulmuyor (satılabilirlik, honeypot sim., kontrat, likidite, V4 hook, holder,
  geliştirici geçmişi, sniper/bundle, sahte hacim). `/minskor` ile eşik.
- **Yükseliş** tarafı sıfırdan, sadece zincir verisiyle (gerçek Fomo fiyatları) kurulacak. DexScreener tabanlı eski
  ölçümler yanlış/iyimserdi (~2-3 kat) → **1 Ekim'de silindi**: momentum v1/v2, rug riski, ÇIK/DİKKAT + takip, ⚡ erken,
  `/mod`, `/gecfiltre`, ikinci dalga, gölge, sonuç ölçümü ve tüm ölçüm komutları (`/karne` `/analiz` `/tarama`
  `/geritest` `/hedef` `/strateji` `/erkenayar` `/gec` `/disari` `/sinyal` `/kazananlar`), Pons izleyici, akıllı cüzdan
  (`/akilli`), ham havuz izleyici, `/pozisyon`, 3x/60 dk araştırma betikleri. Hepsi git geçmişinde.
- Pozisyon büyüklüğü, risk yönetimi, gerçek işlem takibi = sonraki aşama; canlı işlem en son.

## Hedef
Kısa vadeli "vur-kaç", moonshot olursa iyi. Fomo komisyonu %0.5, en az ~$0.95 (başa baş: $5 → 1.47x,
$20 → 1.10x). Fomo içindeki "thesis" yazıları değersiz, kullanılmaz.
Fiyatın zirveden geri çekilmesi tek başına **çıkış sinyali değildir** (kullanıcı kararı); çıkış = kim satıyor.

## Sunucu
- Oracle Always Free, VM.Standard.E2.1.Micro, Ubuntu 24.04, IP `79.76.124.29`, kullanıcı `ubuntu`.
- Cloud Shell'den bağlantı: `ssh -i ~/.ssh/fomo ubuntu@79.76.124.29`
- Yapıştırma bozulmasın diye önce: `bind 'set enable-bracketed-paste off'`
- Güncelleme: `bash ~/Coin/deploy/install.sh` (systemd servisi `rhscanner`, DB `~/Coin/rhscanner.db`)
- Log: `journalctl -u rhscanner -n 50 --no-pager`; hata arama:
  `journalctl -u rhscanner --since "90 min ago" --no-pager | grep -i -E "traceback|error" | tail -25`
- Tek seferlik iş sunucuda: `cd ~/Coin && .venv/bin/python -m rhscanner <komut>` (bot da aynı RPC'yi kullanır;
  RPC'yi yoğun kullanan işlerde botu `sudo systemctl stop rhscanner` ile durdur, sonra `start`).

## Zincir gerçekleri
- Robinhood Chain: chain id 4663, Arbitrum Orbit, ~10 blok/sn.
- Public RPC `https://rpc.mainnet.chain.robinhood.com`: `eth_getLogs` sıkı rate-limit (429), 10k log sınırı,
  eski aralıklarda "log query timed out". Yedek: dRPC `https://robinhood.drpc.org`.
- Blockscout sunucudan Cloudflare 403 veriyor → holder'lar RPC Transfer loglarından hesaplanıyor.
- Fomo emir akışı: entry `0xccc88a9d...`, executor `0xb92fe925...` (sabitler `fomo.py`'de); her işlemde işlem
  yapan cüzdan ve USDG tutarı görünür.
- Pons V2 factory `0x7ed598bc...`, lansman olayı: topic1=token, topic2=curve, topic3=launcher
  (`checks/deployer.py`). Günde ~6-7 bin lansman; `launches.py` hepsini (curve adresiyle) SQLite'ta indeksliyor.
- Pons coini mezuniyete kadar kendi curve kontratında işlem görür: `CurveBuy`/`CurveSell` (topic2=alıcı/satıcı;
  data: eth, token, ücret, vergi — `pons.py`). DexScreener mezuniyet öncesini göstermez.
- Mezun olan coin **yeni bir havuzda yeni hayata başlar** → yaş = lansman ile havuz yaşından genç olanı.
- DexScreener yeni coinleri geç listeler → başlangıç fiyatı yedeği: son Fomo işlemi (USDG ÷ miktar).
- GeckoTerminal (ücretsiz, ağ adı `robinhood`): trend/işlek havuzlar, saatlik OHLCV; ~30 çağrı/dk sınırı, yavaş.
- Uniswap V4 PoolManager, WETH, USDG adresleri `config.py`'de.

## Geliştirme
- Test: `python -m pytest -q` (dev bağımlılıkları `requirements-dev.txt`). Sistem Python'unda `cryptography`
  bozuksa temiz venv kur (`python -m venv ...; pip install -r requirements-dev.txt`). ~55 test.
- CLI: `python -m rhscanner check <adres>`, `trend`.
- Kontratlar: `contracts/`, derleme `scripts/compile_contracts.mjs` (solc 0.8.26, viaIR).

## Mimari (dosyalar, 1 Ekim temizliği sonrası)
`bot.py` Telegram + akış (Fomo'da 10 dk'da `/minalici` alıcı ve `/minhacim` $ → güven taraması → skor ≥ `/minskor`
ise bildirim) · `fomo.py` Fomo işlemleri · `analyzer.py`/`checks/`/`scoring.py` güven skoru (Fomo churn = sahte
hacim bulgusu, bot'un tracker'ından `fomo["churn_share_30m"]` ile) · `launches.py` Pons lansman indeksi
(geliştirici geçmişi) · `hooks.py` V4 hook kaydı · `report.py` güven raporu metni · `flow.py` akış özellikleri
(araştırma; ileride canlı kural). Sunucudaki DB'de eski `signals` tablosu duruyor, artık yazılmıyor/okunmuyor.
Scripts: `fomo_download.py` (zincirden tüm Fomo işlemleri), `data_export.py`/`data_import.py` (`veri` dalı arşivi),
`fomo_supply.py` (arz → FDV), `coin_lifecycle.py` (coin başına yaşam döngüsü, hedefsiz).

## Telegram komutları (hepsi bot.py HELP'te)
`/check <adres>` `/trend` `/minskor` `/minalici` `/minhacim` `/durdur` `/devam` `/durum`

## Veri (araştırma)
**Veri arşivi: GitHub `veri` dalı** (gün başına parquet ~9 MB, `supply.parquet`; 1-3 Eylül + 17 Eylül-1 Ekim; 3-17 Eylül
eksik, indirilmeyecek — kullanıcı kararı). Yeni oturumda: `git fetch origin veri && git worktree add /tmp/veri
origin/veri` → `python scripts/data_import.py /tmp/veri fomo.db` (~1 dk) → `fomo_supply.py fomo.db` (eksik arzlar).
Yeni günler: `fomo_download.py` → `data_export.py fomo.db /tmp/veri` + commit/push (veri dalına). RPC'ye `user-agent`
başlığı gerekir. Fomo olaylarında satış $'ı yok → USDG Transfer(to=executor) ile eşleniyor; Fomo toplu tx'lerinde
~%5 satış fiyatı bozuk → fiyat için ALIM'ları kullan. Araştırma venv'i: `numpy pandas pyarrow scikit-learn`.

## Eski çalışmadan kalan dersler (hâlâ geçerli)
- DexScreener 5-30 dk örnekleriyle ölçülen sonuçlar zincir fiyatlarına göre ~2-3 kat iyimserdi → karar sadece zincir verisiyle.
- Güven skoru yükselişi tahmin etmiyor (hatta ters) ve rug'ı ayırmıyor; güvenlik filtresi olarak kalıyor (eşik 30).
- Sığ havuz kayması önemli: sinyal anındaki havuz USD derinliği medyan ~$5.6k → $100'da alışta ~%2, 3x satışta ~%3.
  Kayma eklenince eski en iyi kural +$14.5 → +$7 (belirsiz). Yeni araştırmada kayma baştan hesaba katılmalı.
- Fomo akışından (alıcı sayısı, hacim, balina payı, tutma, FDV, akıllı cüzdan) kurulan model 13 günde kayma öncesi
  tutarlı küçük kenar gösterdi (en iyi %1-2: +$9-12/işlem, 3x/60 dk ile); küçük FDV + geniş tabanlı alım öne çıkıyordu.
- Pons curve (mezuniyet öncesi) coinleri kötü; mezun olan coin yeni havuzda yeni hayata başlar (yaş = genç olanı).
- Kazananlar çoğu zaman Fomo hacmi gelmeden koşuyor (kapsam sorunu; Fomo dışı V4 swap'lar sonraya bırakıldı).
- Coin yaşam döngüsü (18-30 Eyl, `coin_lifecycle.py`): ~2.070 yeni coin/gün; %86'sı hiç 10 alıcıya ulaşmıyor. ≥10
  alıcılı ~300/gün: ilk alış fiyatına göre zirve ≥2x %62, ≥5x %26, ≥10x %13.5, ≥100x %0.8; 24 s sonra medyan 0.50x,
  son/zirve 0.23; satıcısız %4. 10x+ olanlar yavaş: zirveye medyan 3 saat (%25'i 44 dk, %25'i 24 s+). İlk 10 dk akışı
  10x olanları ayırmıyor (alıcı 9 vs 8) → karar anı ilk dakikalar olmayabilir.
- **"Param 2x olur mu" araştırması (1 Ekim, `scripts/rise_build.py` + `rise_model.py`)**: her coinde dakikada en fazla 1
  aday an (≥3 alıcı/5 dk), giriş +30 sn sonraki alım fiyatı, kayma (havuz derinliği son 15 dk alımlarından) + komisyon
  dahil **net 2x** = fiyat ~2.11x (sığ havuzda 2.28x), 72 saat, iki ardışık alım. Coinin ilk aday anında alsaydık:
  **%31 net 2x** (5 dk %7, 30 dk %19, 1 s %22, 6 s %28, 24 s %31) — 2x'lerin 2/3'ü ilk 30 dk'da. 2x yapanlar önce
  neredeyse düşmüyor (dip medyan 0.98x, %25'i 0.78x altı); yapmayanlar 72 s sonunda medyan 0.30x. "2x'te sat yoksa
  72 s tut" −$16/işlem; zarar-kes 0.8x ile −$3.6 (hâlâ eksi, 2x oranı %23'e iner). Gün gün örnek dışı (7 test günü,
  etiketi kesinleşmiş geçmişle): gradient boosting en iyi %10 **−$1.5 [GA −7.9…+6.6]**, her gün geçmişte en iyi
  sade kural (FDV≤$60k · yaş≤6 s · 0.8x stop) **+$0.7 [−0.7…+1.9]** ≈ başa baş. Dikkat: iki sızıntı bulundu ve
  düzeltildi (havuz derinliği sinyal sonrası işlemlerden / coinin tüm ömründen hesaplanıyordu → sahte +$13-36).
  **Sonuç: sadece Fomo akışıyla "2x olacak" coin seçmenin örnek dışı kârlı kuralı yok.** Dilimlerde en iyi: havuz
  derinliği $9-34k (%45 2x, ~$0), FDV < $200k, büyük 10 dk hacmi; en kötü: sığ havuz < $9k (%28), FDV > $200k.
- **Dış güvenlik / geliştirici / kopya denemeleri (1 Ekim, kullanıcı "bekleme yok" dedi)**: GoPlus (`api.gopluslabs.io`,
  ücretsiz, 4663'ü destekliyor, tek sorguda 1 coin) Pons coinlerinde geçmiş testine yaramıyor: şablon aynı (vergi/mint
  /sahiplik sabit), "creator" fabrika adresi, ayırıyor görünenler (dex'te mi, holder sayısı) bugünkü durum = sızıntı.
  Canlıda ek kontrol olabilir. Pons lansmanları (`scripts/pons_launches.py`, 32 günde 627k, RPC'den dakikalar):
  geliştiricilerin %88'i tek coin; önceki lansman sayısı 2x oranını ayırmıyor (%28-37); dev Fomo kullanıcısı %1.
  Cüzdan kopyalama (`scripts/copy_study.py`): cüzdan başarısı kalıcı değil (yarılar arası sıra korelasyonu ~0.1).
  "Her coinin ilk Fomo alımından 30 sn sonra gir" sonuçları ölçüm hatalarıyla şişti (gelecekte alım olmasını şart
  koşan giriş, %0.5 sanılan $0.95 min. komisyon, tek bozuk fiyat basımları → +$1343 gibi imkânsız değerler); son
  düzeltilmiş sürüm çalıştırılmadı, kullanıcı durdurdu. Kesin ders: 60 dk içinde çıkmak 72 s tutmaktan açıkça iyi;
  $100'da al-sat maliyeti 1x'te ~$5 ($5.6k havuz) – $19 ($1k havuz).
- **"Gözümle 10x-100x görüyorum" kontrolü (1 Ekim, `scripts/ride_test.py`)**: 18-30 Eyl ilk Fomo fiyatından 10x+ yapan
  günde ~44 coin (zirve medyan 19x, zirveye ~4 saat). 10. alıcıda (medyan 12. dk) bunlar zaten 2.4x, kalan yükseliş
  medyan 8.6x (%92'sinde ≥2x kaldı) → yakalanabilir; ama aynı anda 10 alıcıya ulaşan ~264 coin/gün, girişten sonra
  ≥2x %33, ≥10x %6. Her coine girip (k. alıcı +30 sn, kayma+komisyon, coin başı tavan 100x): **3. alıcı + yarısı 2x'te,
  kalanı zirveden %30 düşüşte (iz süren stop): +$10.2/işlem, en iyi %1 hariç +$2.1, 11/11 artı gün** (441/gün);
  5. alıcı +$6.9 (−$0.6), 10. alıcı +$4.2 (−$1.6); tamamını tutmak / sadece 2x hep eksi. Erken giriş + kazananı
  koşturma tek umut veren yapı; kayma varsayılan $5.6k derinlikle (erken anda bilinmiyor) → kötümser maliyetle doğrulanmalı.
- **Kazananların ortak noktaları (1 Ekim, `scripts/winner_study.py` + `winner_report.py`; kullanıcı: "önce tespit, maliyet
  sonra")**: internet araştırması (Pump.fun akademik çalışmaları, GMGN/Axiom kontrol listeleri): en güçlü erken sinyal
  "az işlemle hızlı para birikimi" (büyük, kararlı alımlar), alıcı hızı, hacmin çok cüzdana yayılması, satış olmaması,
  akıllı cüzdan (küçük etki); risk: top10/dev/bundle/sniper/yeni cüzdan payları (bizde arz dağılımı yok). Veride:
  coinin 3./5./10./20. alıcısının geldiği an, sadece o ana kadarki bilgi; etiket = o anki fiyattan 72 s içinde tutulan
  zirve. O andan sonra ≥10x: %6-7 (her kontrol noktasında). **Kazananlar (≥10x) vs <2x medyan**: işlem başı $ 65-81 vs
  40-54, toplam $ ~1.5x, k. alıcıya daha hızlı (5. alıcı 3.9 vs 6.3 dk, 10. alıcı 6.9 vs 12.2 dk), en büyük alıcının
  payı daha düşük, henüz satan yok, FDV daha düşük ($14k vs $18k), lansmana daha yakın, biraz daha fazla akıllı cüzdan.
  Lansmancı geçmişi, yeni cüzdan payı, piyasa genel hareketi ayırmıyor. Model test AUC 0.63-0.66 (20. alıcıda 0.58).
  **Puanlı tarama** (6 kriter: işlem başı ≥$100 · k. alıcıya ≤k/2 dk · satan yok · en büyük alıcı payı ≤0.5 (k≤5) / ≤0.3 ·
  FDV ≤$10k · akıllı cüzdan ≥max(2,k/2)), test döneminde (son %35): 3. alıcıda puan ≥4 → 10x %12 (295 coin), puan
  0-2 → %4-6; 10. alıcıda puan 5-6 → 10x %22, 5x %30 (23 coin), taban ~%6. Yani ~2-3 kat seçicilik; isabet hâlâ ~%10-20.
- **Token transferleri eklendi (1 Ekim, `transfer_download.py` → `transfer_features.py` → `rise_detect.py`)**: 5.1k coinin
  ilk saatlerinin 12.9M Transfer kaydı (RPC, 4 paralel, ~18 dk). Kontrol noktasında holder sayısı/artışı, top10/top1
  payı, dev payı/satışı, sniper payı, Fomo holder payı. **Fomo holder'ların sadece ~%9-20'si** (3. Fomo alıcısı geldiğinde
  coinin zaten ~41-46 holder'ı var) → asıl talep Fomo dışında. Holder özellikleri tahmini az artırıyor: 3. alıcıda test
  AUC (≥5x) 0.627 → 0.669; 5/10/20. alıcıda artış yok. En iyi nokta 3. alıcı, model en iyi %10: ≥2x %54 · ≥5x %29 ·
  ≥10x %16 · ≥100x %1.2 (taban %37 · %14 · %7 · %0.4) → ~2 kat seçicilik, tavan gibi duruyor. En etkili: FDV (küçük),
  top10 payı, transfer yoğunluğu, sniper payı. Kazananlarda dev payı 0 (Pons şablonu), sniper payı biraz yüksek.
  Muhtemel eksik: sosyal sinyaller (X/Telegram/KOL; ücretli) ve Fomo dışı alımlarla tanımlanan daha erken an.
- **Daha erken an: zincirdeki k. curve alıcısı (2 Ekim, `curve_download.py all` → `curve_study.py` → `curve_report.py`)**:
  17-28 Eyl tüm Pons lansmanlarının ilk 6 saatlik curve işlemleri (106.7k coin, 5.5M işlem; zincir geneli sorgu 30k
  blok sınırı, ~15 dk). Fiyat: curve (ETH/USD veriden ~$2.679) + curve ile uyumlu Fomo alımları (12.8k'nın 10k'sı).
  **Uyarı**: sadece ileride Fomo'ya gelen coinlerle bakınca oranlar şişiyor (5. alıcıda ≥5x %39!) = gelecek seçimi; tüm
  lansmanlarla dürüst taban: 5./10./20./40. alıcı (lansmandan 0.1-1 dk, mcap $6-13k) sonra ≥2x %23-28 · ≥5x %6 · ≥10x
  %1.5-2. Model en iyi %10: ≥5x %9-18, ≥10x %2-5 (AUC 0.65-0.72) → ~2-3 kat seçicilik ama mutlak oranlar Fomo 3.
  alıcısından düşük (çöp lansmanlar çok). En etkili: en büyük alıcının payı, dev'in kendi alımı, curve doluluk,
  satış payı, alım büyüklüğü. Sonuç: **Fomo'da alıcı gelmesi kendisi güçlü bir süzgeç**; en iyi tarama anı Fomo 3.
  alıcısı (en iyi %10: ≥2x %54 · ≥5x %29 · ≥10x %16). Not: mezuniyet sonrası Fomo'da işlem görmeyen coinlerde zirve
  eksik ölçülür (curve fiyatı biter) → oranlar alt sınır.
- **Taramayla işlem simülasyonu (2 Ekim, `scripts/scan_trade.py <db> <winners_tx> [eğitim payı]`)**: Fomo 3. alıcısında
  gradient boosting taraması (≥5x, akış + holder özellikleri) dönemin ilk %65'inde (ve ayrıca %50'sinde) eğitilir, kalan
  günlerde işlem: +30 sn, havuz fiyatı, $100, Fomo ücreti (min $0.95), kayma (derinlik bilinmiyorsa kötümser $3k). **Ölçüm
  dersleri**: çıkış/düşüş fiyatı sadece alımlardan okununca kaybedenler iyi görünüyor (çöküş satışlarla olur) → düşüş ve
  süre sonu için tüm işlemler, ölü coin (6 s işlem yok) yarı fiyat; süreli çıkış değeri alımlarla tutulan en yüksek ve
  hedefle sınırlı (tek bozuk satış basımı). Sonuç (test %35 / %50): **seçimsiz** her kuralda eksi ya da ~0 (en iyisi
  "yarısı 2x + kalanı zirveden %30 düşüşte" ~$0; 72 s tut −$41). **Taramanın en iyi %10'u (~24-28/gün)**: yarısı 2x +
  kalanı iz süren %30 **+$26.5 ±13 / +$31.9 ±10**, artı gün 6/6 ve 7/7; "2x'te sat yoksa 1 s sonra çık" +$14.6 ±8 /
  +$11.5 ±7. En iyi %20 (~48-56/gün): +$21 ±8 / +$24.8 ±7 (7/7). En iyi %5: +$54 ±22 / +$48 ±16. 72 s tutmak, iz süren
  %50 ve "2x'te sat yoksa 72 s" kötü. İlk kez seçim + çıkış birlikte örnek dışı pozitif ve hata payı sıfırın üstünde.
  Eksikler: tek dönem (~1 hafta test), canlıda holder özellikleri için transfer okuma gerekir, iz süren stop gecikmesi.

## Sıradaki işler
1. Tarama + "yarısı 2x, kalanı %30 iz süren stop" (yukarıda) daha sağlam doğrulanacak: gün gün kayan pencere,
   sadece Fomo akışı özellikleriyle (canlıda kolay) karşılaştırma; kullanıcı X API'yi (pahalı) şimdilik istemedi.
2. Bulunan kural bota "hızlı bildirim" olarak (flow.py) + Fomo fiyatlarıyla canlı ölçüm (önce bildirimsiz kayıt).
3. Sonraki aşama (kullanıcı onayıyla): pozisyon/risk, gerçek işlem takibi, Twitter/X (ücretli, önce fiyat sor), Solana.
