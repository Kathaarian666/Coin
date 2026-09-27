# Proje notu (yeni sohbetler için)

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
- Branch: `claude/fomo-coin-scanner-app-mhz9rk` (PR açma, kullanıcı istemedikçe).

## Şu anki aşama (kullanıcı kararı, 27 Eylül)
**Parametre ve check sistemini mükemmelleştirme.** Amaç: en iyi taze coinleri doğru anda tespit etmek.
Patlayan coinleri sistemin doğru zamanda yakalayıp yakalamadığı simüle edilir. Testler **sabit test tutarıyla**
(pozisyon büyüklüğü, risk yönetimi, gerçek işlem takibi = sonraki aşama; deploy en son). $5/$20 tartışması yok.

## Hedef
Kısa vadeli "vur-kaç": coin başına $3–5, kayıp küçük, moonshot olursa iyi. Fomo komisyonu %0.5, en az ~$0.95
(başa baş: $3 → 1.93x, $5 → 1.47x). Fomo içindeki "thesis" yazıları değersiz, kullanılmaz.
Fiyatın zirveden geri çekilmesi tek başına **çıkış sinyali değildir** (kullanıcı kararı); çıkış = kim satıyor.

## Sunucu
- Oracle Always Free, VM.Standard.E2.1.Micro, Ubuntu 24.04, IP `79.76.124.29`, kullanıcı `ubuntu`.
- Cloud Shell'den bağlantı: `ssh -i ~/.ssh/fomo ubuntu@79.76.124.29`
- Yapıştırma bozulmasın diye önce: `bind 'set enable-bracketed-paste off'`
- Güncelleme: `bash ~/Coin/deploy/install.sh` (systemd servisi `rhscanner`)
- Log: `journalctl -u rhscanner -n 50 --no-pager`

## Zincir gerçekleri
- Robinhood Chain: chain id 4663, Arbitrum Orbit, ~10 blok/sn.
- Public RPC `https://rpc.mainnet.chain.robinhood.com`: `eth_getLogs` sıkı rate-limit (429), 10k log sınırı,
  eski aralıklarda "log query timed out". Yedek: dRPC `https://robinhood.drpc.org` (sadece ~100 bloklık log).
- Blockscout sunucudan Cloudflare 403 veriyor → holder'lar RPC Transfer loglarından hesaplanıyor.
- Fomo emir akışı: entry `0xccc88a9d...`, executor `0xb92fe925...` (sabitler `fomo.py`'de).
- Pons V2 factory `0x7ed598bc...`, lansman olayı: topic1=token, topic2=curve, topic3=launcher
  (`checks/deployer.py`). Günde binlerce lansman var; `launches.py` hepsini SQLite'ta indeksliyor.
- Her Pons coini mezuniyete kadar kendi curve kontratında işlem görür: `CurveBuy`/`CurveSell`
  (topic1=router, topic2=alıcı/satıcı; data: eth, token, ücret, vergi — `pons.py`). Zincir genelinde ~5 işlem/sn.
  DexScreener mezuniyet öncesi coinleri göstermez; fiyat curve işlemlerinden hesaplanır (ETH fiyatı DexScreener WETH).
- Uniswap V4 PoolManager, WETH, USDG adresleri `config.py`'de.

## Geliştirme
- Test: `python -m pytest -q` (dev bağımlılıkları `requirements-dev.txt`; honeypot testleri eth-tester ile).
- CLI: `python -m rhscanner check <adres>` (JSON rapor), `python -m rhscanner trend`.
- Kontratlar: `contracts/`, derleme `scripts/compile_contracts.mjs` (solc 0.8.26, viaIR).

## Yapılanlar (özet)
Fomo akışı izleme ve bildirim · güven skoru (kontrat, likidite, V2 honeypot simülasyonu, V4 hook tanıma,
holder dağılımı, lansman: dev/sniper/bundle) · momentum skoru · çıkış sinyalleri (ÇIK/DİKKAT, 5/15/30 dk) ·
akıllı Fomo cüzdanları · komisyon/başa baş · sonuç kaydı ve `/karne` · geliştirici geçmişi · sahte hacim tespiti ·
Pons lansman indeksi (sunucuda doğrulandı: ~329 bin coin).

## Sıradaki işler
1. **Karne incelemesi ve kalibrasyon** (birkaç gün veri birikince): `/karne 24`, `/karne 72` çıktılarını
   kullanıcıyla incele. Momentum ağırlıkları ve eşikler (min skor, min alıcı, min hacim) buna göre ayarlanacak.
   Kayıtlı özellikler (`outcomes.py` → `signals.features`): momentum özellikleri, dev/sniper/bundle payı,
   geliştirici geçmişi, sahte hacim, likidite, FDV, sosyal linkler, bulgu kodları. Fikirler: momentum eşiği ile
   bildirim filtreleme, piyasa rejimine göre değişen eşikler, geliştirici/wash bulgularının ağırlığını veriyle ayarlama.
   İlk tur (72 saatlik veri): `/minmomentum` eklendi (sunucuda 45), `/karne` güven/momentum kırılımları ve
   `/bulgular` eklendi. `liq_usd_low` high→low (bu coinler ortalamadan iyi), `v4_common_hook` low→medium
   (rug %17). İlk 24 saatte bildirimlerin 1s 2x oranı %27'ye çıktı. 30 Eylül'de `/karne 72` +
   `/bulgular 72` ile tekrar bak. ÇIK sinyalleri isabetli (10 sinyal: %50'si 1s sonra aşağıda, kaçırılan 1.5x yok).
   168 saatlik veriyle karar verildi: `/minmomentum 70` (70+ %20 vs 45-69 %11 1s 2x)
   ve `/minskor 30` (güven 30-49 en iyi grup: %42 1s 2x; rug her aralıkta %9-11, güven rug'ı ayırmıyor).
2. **Sinyal isabeti araştırması** (27 Eylül): `/analiz` (özellik dilimleri → hangi özellik kazandırıyor) ve
   `/kazananlar` (GeckoTerminal'den 10x+ coinler, bot yakaladı mı) eklendi. GeckoTerminal ücretsiz ama yavaş
   (~3-5 dk). Sonuçlara göre sıradaki: C) ikinci dalga bildirimi (coin başına tek bildirim, sonraki dalgalar
   kaçıyor), D) yeni özellikler (alıcı başına alım $, holder artış hızı, Fomo dışı alıcı), E) çıkış stratejisi
   simülasyonu, F) piyasa rejimi. Araştırma: en güçlü tahminci az işlemle hızlı biriken para (Pump.fun çalışması),
   bot oranı negatif, Telegram varlığı ~9x mezuniyet, akıllı para etkisi karışık.
   İlk `/analiz` (7 gün, 1212 sinyal): büyük kazananlar genç + küçük FDV + hacmi tamamen Fomo'dan. FDV <$17k 5x %39
   vs >$109k %2; yaş >30 saat 5x %4; Fomo payı %100 5x %31; güven skoru ters; hızlanma ayırmıyor; sniper varsa
   daha iyi. `/kazananlar` (3 gün, 6 kazanan): HOODS 45x rallinin başında bildirildi; ROBINPEPE 291x zirvede
   (FDV $3M) bildirildi; BROBIN 8 alıcıyla gölgede kaldı (12x); FILR/SI Fomo'da hiç yoktu.
   → Momentum v2 (`momentum.tuned_points`): FDV <$20k +15, >$110k −10; yaş >30s −15 (taze bonusu kalktı);
   Fomo payı ≥%95 +10; ince likidite cezası kalktı; balina eşikleri 0.42/0.62; hızlanma +12→+4. Varsayılan
   kapalı; `/geritest` ile yeni yarıda v1'den iyiyse `/momentumv2 ac`. v1 ve v2 her sinyalde features'a yazılıyor.
   `/geritest` (yeni yarı): v2 130 bildirim 2x %31.5 / 5x %32.3 / rug %6.2 vs v1 160 bildirim %26.2 / %24.4 / %7.5.
   **27 Eylül'de sunucuda `/momentumv2 ac` yapıldı.** Canlı hedef: bildirimlerde 1s 2x > %26, 5x > %24.
   C) İkinci dalga ölçüm modunda eklendi (kind `wave2`, bildirim yok): ilk sinyalden ≥1 saat (≤3 gün) sonra,
   30-60 dk önce sakin (alıcı < eşik/2) ve şimdi bildirim eşiğini geçen coin; v2 momentum + fiyat/ilk sinyal
   kaydedilir, `/karne`'de ayrı grup. İyi çıkarsa bildirim açılacak.
   E) `/strateji`: çıkış kuralları geçmiş bildirimlerin fiyat yolunda, komisyon dahil (`strategy.py`).
   İlk `/strateji` (300 bildirim): $5'ta en sağlam "1 saat tut" (+$127, en iyi işlem olmasa +$34); 2x/3x'te satmak
   zararlı; 2-4 saat tek büyük işleme bağlı. $20'da 1 saat tut +$2660 (en iyi hariç +$2216, kazanan %29): $0.95
   minimum komisyon $5'ı yapısal olarak eziyor. İyimser: tepki süresi, sığ havuz kayması, ve "0 ÇIK eşleşti"
   (başlangıç fiyatı olmayan bildirimler sonuçlardan düşüyor olabilir — teşhis gerekiyor).
   Kullanıcı kararı: şu an geliştirme aşaması; gerçek işlem takibi (journal) istenmedi, geri alındı. Deploy en son.
   Veri kalitesi: DexScreener yeni coini listelemeden gelen sinyallerin başlangıç fiyatı yoktu → karne/analiz/
   strateji'den sessizce düşüyordu (şüphe: "0 ÇIK eşleşti"). Artık yedek fiyat son Fomo işleminden (USDG ÷ miktar,
   decimals rapordan, yoksa 18); `/karne` başında ölçülemeyen sinyal sayısı gösteriliyor.
   Gölge sinyallere de piyasa verisi (FDV, likidite, yaş, Fomo payı, v1/v2) kaydediliyor → `/geritest` sonunda
   "küçük coinlerde alıcı eşiği 8 olsaydı" bölümü (BROBIN vakası). F) Piyasa rejimi: her sinyalde
   `market_buyers_1h` (1 saatte tüm Fomo alıcıları), `/analiz`'de dilimli.
   `/kazananlar` artık ana zamanlama testi: varsayılan 7 gün, her kazanan için bugünkü eşiklerden hangisinin
   engellediği ve değeri (`outcomes.blocking_gates`), "bugünkü eşiklerle yakalanırdı X/Y · erken (≤2x) Z".
   `/strateji` sabit $100 test tutarıyla (pozisyon ayarından bağımsız). `/tarama`: min momentum (v2) ×
   min güven ızgarası → bildirim sayısı, 2x/5x/rug, 5x'lerin yakalanan payı (`outcomes.parameter_sweep`).
   Min alıcı taraması gölgelerde FDV biriktikçe `/geritest` sonundaki bölümle.
   İlk `/tarama` (463 sinyal, 75 tanesi 5x): güven eşiği (0-40) sonucu neredeyse değiştirmiyor; momentum dilimleri
   70-74 %6, 75-79 %11, 80-84 %22, 85+ %37 5x → **`/minmomentum 75` yapıldı** (253→220 bildirim, 5x %26.5→%29.5,
   yakalama %89→%87). Rug her eşikte ~%10 → rug riski puanı (`rugrisk.py`, ölçüm modu, filtre yok): alıcı başına
   <$74 +25, tutma <0.8 +20, Fomo payı <%23 +15, 10 dk alım <$550 +10, yaş <14 dk +10. Bildirimde ≥20 ise satır,
   `/karne`'de düşük/orta/yüksek kırılımı, `/analiz`'de özellik, `/tarama` sonunda "rug riski <60/<40/<20" filtresi
   (kalan 5x'ler ve rug oranı). Geçmiş sinyaller için de kayıtlı özelliklerden hesaplanıyor.
   Rug filtresi sonucu (221 bildirim): puan rug'dan çok oynaklığı ölçüyor — 60+ %30 rug / 0 5x (10 bildirim),
   40-59 %11 rug / **%40 5x**, 20-39 %13 / %29, <20 %7 / %29. <40 filtresi 14 kazanan kaybettiriyor. → `/maxrug`
   komutu (varsayılan kapalı; **sunucuda `/maxrug 60` yapıldı**), bildirim uyarısı sadece 60+. Rug ~%10 sabit;
   odak kazananlarda. Güncel set: güven ≥30, momentum v2 ≥75, rug <60, alıcı ≥10, 10 dk alım ≥$500.
   **`/kazananlar` 7 gün (8 kazanan ≥10x) bugünkü setle 1/8 yakalanırdı, 0 erken.** HOODS (başta bildirilmiş, 45x)
   bugün v2 momentum 62 < 75 ile ENGELLENİR (v1 72 idi; v2 taze bonusu ve hızlanmayı düşürdü). ROBINPEPE'nin zirve
   bildirimi doğru engelleniyor. BROBIN alıcı 8/hacim $189/momentum 74. SW 17x başlangıç fiyatı yok. → `/tarama`
   ile çelişki: /tarama'nın 5x'i tek DexScreener ölçümünün max'ı (sığ havuz sıçraması olabilir). Eklendi:
   `held_all` = art arda iki ölçümde tutulan çarpan, "kalıcı 5x" (/tarama recall'u artık kalıcıya göre, /analiz,
   /karne de gösteriyor) ve `/sinyal <adres>` (bir coinin tüm kayıtlı özellikleri + sonucu). Parametreler
   değiştirilmedi; kalıcı 5x ile /tarama yeniden bakılacak, gerekirse v2 ağırlıkları (taze/hızlanma) gözden geçirilecek.
3. **Twitter/X verisi** (opsiyonel): sadece karne verisi olduktan sonra ve ucuz bir 3. parti API ile
   (~$20/ay civarı); kullanıcıya fiyatla sorulacak.
4. ~~Mezuniyet öncesi Pons takibi~~ — **denendi, işe yaramadı, kapatıldı** (27 Eylül). `pons.py` curve
   alım/satımlarını okuyup 8+ ve 4+ alıcı eşiğinde sinyal + bariz çöp filtresi uyguluyordu; `pons-backfill` ile
   3 günlük veri (~9k sinyal): filtreden geçenler bile medyan 1s sonu 0.70–0.78x, 5x %1.5–1.9 (Fomo bildirimleri
   %14.7). Erken eşik daha iyi değil → sorun zamanlama değil, coinlerin çoğu satmak için çıkarılıyor. Fomo'da hacim
   gelmesi zaten güçlü bir eleme. Kod duruyor, `ENABLE_PONS_WATCHER=1` ile açılır (RPC yükü getirir).
5. **V3/V4 honeypot simülasyonu** (şu an sadece V2; Fomo'da başarılı satışlar honeypot olmadığını gösteriyor).
6. **Solana** — ayrı proje olarak, Robinhood tarafı oturduktan sonra.
