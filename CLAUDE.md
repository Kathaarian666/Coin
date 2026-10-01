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

## Şu anki aşama (kullanıcı kararı, 27 Eylül)
**Parametre ve check sistemini mükemmelleştirme.** Amaç: en iyi taze coinleri **doğru anda** tespit etmek.
Patlayan coinleri sistemin doğru zamanda yakalayıp yakalamadığı simüle edilir. Testler **sabit test tutarıyla**
($100). Pozisyon büyüklüğü ("az güvenirsek $20, çok güvenirsek $100"), risk yönetimi, kullanıcının gerçek işlem
takibi = **sonraki aşama**; canlı işlem en son. Kullanıcı bu aşamada kendi işlemlerini kaydetmeyi İSTEMEDİ
(/aldim-/sattim ve /cuzdan denendi, geri alındı).

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
  bozuksa temiz venv kur (`python -m venv ...; pip install -r requirements-dev.txt`). ~120 test.
- CLI: `python -m rhscanner check <adres>`, `trend`, `pons-backfill <gün>`.
- Kontratlar: `contracts/`, derleme `scripts/compile_contracts.mjs` (solc 0.8.26, viaIR).

## Mimari (dosyalar)
`bot.py` Telegram + akış · `fomo.py` Fomo işlemleri · `analyzer.py`/`checks/` güven skoru · `momentum.py`
momentum (v1/v2, `tuned_points`) · `rugrisk.py` rug riski · `outcomes.py` sinyal kaydı, fiyat örnekleri,
karne/analiz/tarama/geritest hesapları · `report.py` Telegram metinleri · `winners.py` GeckoTerminal kazanan
otopsisi · `strategy.py` çıkış kuralı simülasyonu · `launches.py` Pons indeksi · `pons.py`/`pons_backfill.py`
Pons curve (kapalı) · `wallets.py` akıllı cüzdanlar · `exits.py` ÇIK/DİKKAT.

**Sinyal türleri** (`signals.kind`): `alert` (bildirim gitti; `features.early` = ⚡ erken), `filtered` (analiz
edildi, eşiğe takıldı), `shadow` (eşiğin yarısını geçen, analiz edilmeyen karşılaştırma grubu; FDV/likidite/v1/v2
de kaydediliyor), `wave2` (ikinci dalga, ölçüm), `exit`/`caution` (ÇIK/DİKKAT), `pons*` (kapalı). Her sinyalde
fiyat örnekleri 0,5,10…1440. dk. Sonuç ölçüleri: `max_60`, `max_all` (24s tekil en yüksek), **`held_all` (art arda
iki örnekte tutulan — "kalıcı"; sığ havuz sıçramalarını eler, esas ölçü bu)**, `ret_60`, `rugged`.

## Güncel canlı ayarlar (sunucuda, 27 Eylül)
güven (`/minskor`) ≥30 · momentum **v2** (`/momentumv2 ac`) ≥75 (`/minmomentum`) · `/maxrug 60` ·
alıcı ≥10 (`/minalici`) · 10 dk Fomo alımı ≥$500 (`/minhacim`) · **`/erken 90`** (30 Eylül'de 85→90 önerildi) · Pons takibi kapalı (`.env`'de satır yok).
Geçmiş veride bu set: bildirimlerin kalıcı 5x ~%22, 5x yapanları yakalama ~%90, rug ~%10.

## Telegram komutları (hepsi bot.py HELP'te)
Ayar: `/mod erken|hepsi` `/minskor` `/minmomentum` `/gecfiltre ac|kapat` `/momentumv2 ac|kapat` `/maxrug N|kapat` `/erken N|kapat` `/minalici`
`/minhacim` `/pozisyon` `/durdur` `/devam` `/durum`
Ölçüm: `/karne [saat]` (gruplar, momentum/güven/rug kırılımı, ⚡ erken, ikinci dalga, ÇIK isabeti, ölçülemeyen
sayısı) · `/analiz [saat]` (her özellik üç dilim: 2x/5x/kalıcı/rug) · `/bulgular [saat]` (güven bulgusu bazında) ·
`/tarama [saat]` (min momentum × min güven ızgarası + rug filtresi, kalıcı 5x yakalama) · `/geritest [saat]` (v1 vs
v2 eski/yeni yarı; küçük coin alıcı eşiği 8; erken kural A/B × momentum 0-90) · `/kazananlar [gün] [kat]`
(GeckoTerminal 10x+ coinler; bot yakaladı mı, hangi eşik engelledi, her birinin `/sinyal` komutu; ~8 dk sınırı) ·
`/sinyal <adres>` (coinin tüm kayıtlı sinyalleri ve sonucu) · `/strateji [saat]` (çıkış kuralları, sabit $100) · `/disari [saat]` (erken sinyal listesi, zincir backtesti için) · `/erkenayar [saat]` (erken kural ayar ızgarası) · `/hedef [saat]` (2x al-çık: grupların işlem başı $, en iyi çıkış kuralları, eski/yeni yarı) · `/gec [saat]` (geç kalma: ilk görülmeden bu yana fiyat artışı/süre,
bildirim anı 5 dk/1 s fiyat değişimi, artış sınırı taraması).
Diğer: `/check <adres>`, `/trend`, `/akilli`.

## Yapılanlar ve bulgular (kronolojik özet)
1. **Temel sistem**: Fomo akışı izleme ve bildirim · güven skoru (kontrat, likidite, V2 honeypot sim., V4 hook,
   holder dağılımı, lansman dev/sniper/bundle, geliştirici geçmişi, sahte hacim) · momentum · ÇIK/DİKKAT
   (5/15/30 dk, "kim satıyor") · akıllı cüzdanlar · sonuç kaydı · Pons lansman indeksi (400 bin+).
2. **İlk kalibrasyon**: `liq_usd_low` high→low (bu coinler ortalamadan iyi), `v4_common_hook` low→medium (rug %17).
3. **`/analiz` (7 gün)**: büyük kazananlar **genç + küçük FDV + hacmi tamamen Fomo'dan**. FDV <$17k 5x %39 vs
   >$109k %2; yaş >30 saat 5x %4; güven skoru yükselişi TERS tahmin ediyor ve rug'ı ayırmıyor (her aralıkta ~%10);
   hızlanma tek başına ayırmıyor; sniper varsa daha iyi.
4. **Momentum v2** (`momentum.tuned_points`): FDV <$20k +15, >$110k −10; yaş >30s −15 (taze bonusu kalktı);
   Fomo payı ≥%95 +10; ince likidite cezası kalktı; balina 0.42/0.62; hızlanma +12→+4. `/geritest` kalıcı 5x ile
   de doğrulandı: yeni yarı v1 %18.6 → v2 %26.0, v2'nin çıkardıkları %0. **Açık.**
5. **`/tarama`**: güven eşiği 0-40 neredeyse fark etmiyor; momentum dilimleri 70-74 zayıf → **75**. 80 daha isabetli
   ama HOODS'u (düzeltilmiş v2 ≈77) kaçırır.
6. **Rug riski** (`rugrisk.py`: alıcı başına <$74 +25, tutma <0.8 +20, Fomo payı <%23 +15, 10 dk alım <$550 +10,
   yaş <14 dk +10): rug'dan çok **oynaklığı** ölçüyor. 60+ %30 rug / 0 kazanan → `/maxrug 60` (kazanan kaybı 0);
   40-59 en çok 5x veren dilim (%40) → <40 filtresi kazananları götürür. Uyarı yalnız 60+.
7. **`/kazananlar` (7 gün, 8 kazanan ≥10x)**: HOODS 45x rallinin başında bildirildi; ROBINPEPE 291x zirvede
   (FDV $3M) bildirildi (v2 artık bunu engelliyor, doğru); BROBIN (12x) 8 alıcıyla gölgede kaldı; SW (17x) başlangıç
   fiyatı yok; FILR/SI Fomo'da hiç yok (kapsam dışı). Sonra bulunan **yaş hatası** (lansman yaşı 2900 dk, havuz
   2-3 saatlik → v2 −15) HOODS'u haksız engelliyordu → **düzeltildi**.
8. **Erken giriş (⚡)**: HOODS gölgesi bildirimden 18 dk önce: son 5 dk 5 alıcı / önceki 0, alıcı başına $211,
   tutma 1.0, momentum 86 → 116x (kalıcı 45x). Kural A (son 5 dk ≥5, önceki ≤1, alıcı başına ≥$100, tutma ≥0.9)
   gölgelerde: şartsız 180 sinyal kalıcı 5x %7 (gürültü); **momentum ≥85: 11 sinyal kalıcı 5x %45.5, 1s sonu medyan
   3.29x** → `/erken 85` açıldı (kural 2 Ekim'de değişti, bkz. 17) (A'ya uyan coin 10 alıcı beklenmeden analiz edilir; geçemezse normal yola açık).
   Kural B (kalabalık, BROBIN tipi: son 5 dk ≥8, önceki ≤1, tutma ≥0.9; alıcı başına $24) 4 sinyal → ölçümde.
9. **`/strateji` (sabit $100)**: en sağlam çıkış "1 saat tut"; 2x/3x'te satmak zararlı (kazananları keser);
   24 saat tutmak kötü; 2-4 saat tek büyük işleme bağlı. $5'ta $0.95 min. komisyon yapısal olarak eziyor.
   Simülasyon iyimser: tepki süresi ve sığ havuz kayması yok.
10. **Veri kalitesi düzeltmeleri**: yeni coinde DexScreener fiyatı yoksa Fomo işlemi fiyatı; `/karne` ölçülemeyen
    sinyal sayısını gösteriyor; kalıcı 5x ölçüsü; `_usd` biçim hatası (bildirimde "$0k") düzeltildi; `/kazananlar`
    8 dk süre sınırı + hata olursa cevap.
11. **İkinci dalga** (`wave2`, ölçüm): ilk sinyalden 1 saat-3 gün sonra, 30-60 dk önce sakin, şimdi bildirim
    eşiğini geçen coin kaydediliyor (HOODS 26 saat sonra kaydedildi). Bildirim yok.
12. **Piyasa rejimi**: her sinyalde `market_buyers_1h`; `/analiz`'de dilimli (henüz yorumlanmadı).
13. **30 Eylül canlı doğrulama** (`/karne 72`, `/geritest` 168s): bildirim 323 → kalıcı 5x %16.1 (beklenen ~%22
    değil ama filtre %7.3 / gölge %8.1'in iki katı), rug %8.7, 1s sonu medyan 1.0x. ⚡ erken 25 → kalıcı 5x %24,
    1s sonu medyan 1.61x, rug %4 (en iyi grup). Geritest erken A: mom ≥80 %25.5 (47), ≥85 %39.3 (28), ≥90 %55
    (20) → 85-89 dilimi 8 sinyal 0 kalıcı 5x, 80-84 çok zayıf → **80'e inme; `/erken 90` önerildi** (geçemeyen
    normal yola düşer). Kural B zayıf (10 sinyal, 1s sonu 0.75x). Alıcı eşiği 8: 2 sinyal ikisi de kalıcı 5x (az).
    İkinci dalga mom 70+ kalıcı 5x %10.8 < bildirim → bildirim açılmadı. Güven <30 (14) %21.4, 30-49 %14.7, 70+
    %12.4 → yine ters. **ÇIK tutmuyor**: 126 sinyal, 1s sonra aşağıda %42.9, kaçırılan 1.5x %22 (eski 10 sinyallik
    iyi sonuç tutmadı); DİKKAT 13 sinyal %61.5 aşağıda. Son 72 saatte ~700 Pons sinyali → sunucuda Pons izleyici
    açık olabilir (`.env` kontrolü istendi). `/geritest` hatası düzeltildi: v2 canlıyken "v1" sütunu v2 puanını
    kullanıyordu (artık `features.momentum_v1`). `/kazananlar` (7g, 10x+): 5 kazanan — ROBINPEPE zirvede
    bildirilmiş (232x'te; v2 artık engelliyor, doğru), HLCAT/VRAX gölgede ama bot ilk gördüğünde zaten 25x/14x
    olmuşlardı (sonrası en fazla 1.9x/1.4x), PRIORS 282x/2s ve LIQCAT 47x Fomo'da hiç görülmedi. → Kaçırılanlar
    eşik sorunu değil, **zamanlama/kapsam sorunu**: büyük koşu Fomo hacmi gelmeden bitiyor. Eşik düşürmek çözmez.
    `/kazananlar 7 5`: 8 kazanan — 4'ü Fomo'da hiç görülmedi (PRIORS, LIQCAT, HOODIE, NFLOAT), 3'ü geç görüldü,
    1'i doğru anda yakalandı (VRAX 0xc608…: başlangıcın 0.4x'inde bildirim, alıcı 56, mom 100 → sonra 13x).
    Kapsamı Fomo dışı alımlara (V4 swap) genişletmek: kullanıcı **sonraya bıraktı** (ucuz ölçüm fikri: GeckoTerminal'de
    erken yükselip Fomo'da görünmeyenleri bildirimsiz kaydetmek). `/tarama 72` (540 sinyal, 68 5x): ayar değişmedi.
    Güven 30→0: +8 bildirim, +2 5x (az; güven skoru satılabilirlik riskini de tuttuğu için 30 kaldı). Momentum
    75-79 dilimi (46 bildirim) kalıcı 5x ~%9 ≈ gölge seviyesi, 80'e çıkmak yakalamayı %79→%73 düşürür → 75 kaldı;
    bu dilim risk aşamasında küçük pozisyon adayı. Rug <40 7 kalıcı 5x kaybettirir → `/maxrug 60` kaldı.
14. **Kullanıcı hedefi (30 Eylül): "daha az ama isabetli bildirim, kalıcı 5x %30+"** (şu an ~%16). Hipotez: sorun
    zamanlama. `/gec` eklendi: bildirim fiyatı ÷ coinin ilk görüldüğü (gölge) fiyat (`runup_first`, geçmiş veriden
    hesaplanıyor), geçen dk; `change_m5`/`change_h1` artık her sinyalde kaydediliyor. Bunlar `/analiz`'de de var.
    İlk `/gec 168` (681 bildirim, 89 kalıcı 5x): artış sınırı işe yaramıyor (<3x: kalıcı %13.1→13.6, 1 kazanan
    kaybı; 3x+ dilimi 35 sinyal rug %37 ama küçük). En büyük zayıf dilim: gölgeden bildirime fiyat 1–1.5x (299,
    kalıcı %8.7 ≈ gölge seviyesi); 1.5–3x %21.9. "Önceden görülmemiş" 64 bildirim %26.6 — ama `signals` token+tür
    başına tek kayıt olduğundan bu grup eski dalgadan dönenleri de içeriyordu → `first_seen` (self/old/unpriced/
    shadow) ayrımı ve momentum ≥85 kırılımı eklendi. İkinci `/gec 168`: "önceden hiç görülmemiş" yok; önceki dalga
    (gölge >24s) 26 bildirim kalıcı %3.8; gölge fiyatı yok (çok yeni coin) 62 → %25.8; mom ≥85 & 3x+ 24 → %0, rug
    %46; mom ≥85 & 1–1.5x 138 → %12.3; mom ≥85 & <1x %23.6, 1.5–3x %25.
15. **1 Ekim**: `/gecfiltre ac|kapat` (varsayılan kapalı; `late_filter`): önceki dalga (ilk görülme >24s) ve ilk
    görülmeden 3x+ yükselmiş coinlere bildirim yok (`filtered` kaydedilir; `runup_live`/`first_age_min`/`late_block`
    özelliklerde). `/gec`'e "fiyat hareketini bekle" simülasyonu: bildirimden 60 dk içinde %20/30/50 yükselince
    gir (`confirm_entry`, örnek fiyatlarından), 1–1.5x dilimi ve tüm bildirimler için. **Sonuç (770 bildirim, 99
    kalıcı 5x): beklemek ZARARLI** — %20 bekle: girilen 348, girişten kalıcı 5x %10.1 (hemen %12.9), kazananların
    sadece 35/99'u kalır; 1–1.5x dilimde de 30→13. Kazananlar hızlı ve büyük gidiyor; bekleme fikri bırakıldı.
    `/gecfiltre` (3x+ ve önceki dalga) 71 bildirim eler, 2 kazanan kaybı → kalıcı ~%12.9→~%13.9, rug düşer.
    %30 hedefi mevcut özelliklerle hacimli bir dilimde yok: en iyi dilimler ~%24-26 (mom ≥85 & <1x veya 1.5–3x,
    gölge fiyatı yok = çok yeni coin), %30+ sadece ⚡ erken ≥90 (az sinyal).
16. **YÖN DEĞİŞİKLİĞİ (1 Ekim, kullanıcı kararı)**: tek yönteme odaklan = **⚡ erken sinyal**; hedef artık kalıcı 5x
    değil **"2x al-çık"** (sonra 5-10x giderse gitsin). Gerekçe: erken canlıda 1s 2x %44, 1.5x %64, 1s sonu medyan
    1.61x, rug %4 (normal: %30 / 1.0x). İki sınıf fikri bırakıldı (kullanıcı tek akış istiyor). Eklenenler:
    `/mod erken|hepsi` (`alert_mode`; erken modda normal bildirimler gönderilmez ama `alert` + `features.muted`
    olarak kaydedilir, takip/ÇIK yok; karnede 🔕 Sessiz grubu — "Bildirim gidenler" sessizleri de içerir) ·
    `/hedef [saat]` (`strategy.target_exit/target_table`: hedef 1.5/2/3x × süre 30/60/120 dk × stop yok/0.7x;
    hedef ancak art arda iki örnekte tutulursa satılır; sabit $100 + komisyon; eski/yeni yarı $; gruplar: ⚡ erken,
    normal, kural A gölgeleri mom ≥85/≥90; ≥3 saatlik sinyaller). İlk `/hedef 168`: ⚡ erken (33) "2x/60dk" +$41/işlem,
    en iyi "3x'te sat yoksa 60-120 dk" +$70-80 (eski yarı +$115-128, yeni +$28-36); gölge A ≥90 (28) 3x/60 +$106,
    kârlı %89, iki yarı da pozitif; normal (733) 3x/30 +$22. 3x hedefi her grupta 2x'ten iyi. Şüphe: süre dolunca
    tek ölçümdeki iğneden satılıyordu → düzeltildi (sonraki ölçümle min); "5 dk geç giriş" satırı eklendi. Kayma
    (sığ havuz) hâlâ yok. Düzeltilmiş `/hedef 168`: sonuç sağlam — 3x/60dk: ⚡ erken +$69 (5 dk geç ~+$43), gölge A
    ≥85 +$84 (geç +$52), ≥90 +$101 (geç +$67), normal +$14 (geç 2x kuralı −$5). **Seçilen çıkış: "3x'te sat, yoksa
    60 dk'da çık"** (stop 0.7 tutarlı fark yok). Hız kritik: 5 dk gecikme kazancın 1/3–1/2'si.
17. `/erkenayar [saat]` (varsayılan 336): erken kural ızgarası (son 5 dk alıcı 3-8 · önceki ≤0-2 · alıcı başı
    $0-200 · tutma 0.8-1.0 · mom 80-95; `outcomes.early_grid`) gölgelerde (alıcı eşiği altı), 3x/60dk $; eski
    yarıya göre sıralı, yeni yarı sınav, 5 dk geç; her yarıda ≥8 sinyal. İlk çıktı (1863 gölge): **momentum ≥90 asıl
    belirleyici** (tüm üst sıralar); eski kural 5/≤1/$100/0.9: 28 sinyal, yeni yarı +$83, geç +$67. Yeni **canlı kural
    A = son 5 dk ≥5 · önceki 5 dk 0 · alıcı başı ≥$50 · tutma ≥0.8** (+ `/erken 90`): 46 sinyal, eski +$134 (12),
    yeni +$78 (34), geç +$64, kârlı %83 → aynı kalite, ~1.6x sinyal. (son 5 dk 3/4/5 fark etmiyor.)
18. **Zincir backtesti (2 Ekim, devam ediyor)**: kullanıcı 3 gün beklemek istemiyor. `scripts/fomo_download.py <gün>
    <db>` tüm Fomo işlemlerini zincirden indirir (Claude bulut ortamından da çalışır; RPC'ye `user-agent` başlığı
    gerekir, yoksa 403). Günde ~300k işlem; 14 gün ~3 saat. **Fomo olaylarında satışların $ tutarı yok** → USDG
    `Transfer(to=executor)` logları ayrıca çekilip tx'e göre eşleniyor. `scripts/fomo_replay.py <db>`: her alımda
    kural A özellikleri, ilk eşleşme = sinyal; gerçek Fomo fiyatlarıyla 30/60/120 sn gecikmeli giriş, 2x/3x hedef
    (birisi o fiyattan sattıysa) yoksa 60. dk; FDV (1B arz varsayımı) ve Fomo yaşı ile ızgara, eski/yeni yarı.
    Momentum ve güven zincirden hesaplanamaz. Veri hataları düzeltildi: satış $'ı tx'teki en büyük USDG transferi
    olduğundan Fomo'nun toplu tx'lerinde ~%5 satış 2x+ pahalı görünüyordu → hedef sadece art arda iki ALIM fiyatıyla,
    saat sonu fiyatı alımların medyanı. Kalibrasyon: gevşek kural "1s 2x" %22 = botun gölge ölçümü (tutarlı).
    **Sonuç (14 gün, 4.6M işlem, 120k aday an, 5.8k coin)**: sadece Fomo verisiyle (momentum yok) en iyi kurallar
    son 5 dk ≥8 alıcı · önceki 0 · alıcı başı ≥$200 · tutma ≥0.9-1.0 · FDV ≤$50k · yaş ≤6s: ~5 sinyal/gün, 3x/60dk
    ham ort. 30-60 sn gecikmeyle +$22-28, en iyi %5 hariç +$9-13, **medyan −$23** (çoğu işlem ~%23 kaybeder, ~%25'i
    3x yapar), iki yarıda da pozitif. Canlı kuralın Fomo kısmı (5/0/$50/0.8, momentumsuz): ham +$12-18, %5 hariç
    −$11 → momentum filtresi şart. Botun `/hedef` ölçümü (erken mom ≥90: +$70-100) zincir fiyatlarıyla
    doğrulanmadı — sıradaki adım: `/disari` (erken bildirimler E + kural A gölgeleri mom ≥80, satır başı
    "adres12 unix kod mom") çıktısını kullanıcı yapıştırır → `scripts/fomo_check_signals.py <db> <txt>` gerçek
    fiyatlarla puanlar (veri yoksa önce `fomo_download.py 14`). **Sonuç (2 Ekim, 127 ölçülen sinyal, ~7 gün)**:
    3x/60dk, 30-60 sn gecikme — A gölge mom ≥90 (47): ort +$32-44, %5 hariç +$20-33, medyan −$30, hedef %28-30,
    kârlı %40-45 (en iyi grup); ⚡ erken bildirim (32): ort +$10-13, %5 hariç ~$0, medyan −$21-26 (gölgeden ~15-40 sn
    sonra gidiyor; bir kısmı eski /erken 85 ile); mom 85-89 (25): ~$0 / %5 hariç −$10-14; mom 80-84 (23): −$9-12.
    → **momentum ≥90 gerçekten ayırıyor** ama **botun `/hedef` ölçümü ~2-3 kat iyimser** (DexScreener 5-30 dk
    örnekleri). Kenar küçük ve örnek az (std hata ~±$13). Gerçek parayla büyük işlem önerilmedi.

## Denenip bırakılanlar / yapılamayanlar
- **Mezuniyet öncesi Pons takibi**: `pons.py` + `pons-backfill` ile 3 gün ~9k sinyal: filtreden geçenler bile medyan
  1s sonu 0.70–0.78x, 5x %1.5–1.9 (Fomo bildirimleri %14.7). Erken eşik (4+ alıcı) daha iyi değil → coinlerin çoğu
  satmak için çıkarılıyor; Fomo'da hacim gelmesi zaten güçlü eleme. Kod duruyor, `ENABLE_PONS_WATCHER=1` ile açılır
  (RPC yükü getirir, rate-limit sorunlarına katkı yapıyordu).
- **Kullanıcının gerçek işlem takibi** (/aldim-/sattim elle, sonra /cuzdan ile zincirden otomatik): bu aşamada
  istenmedi, geri alındı. Risk yönetimi aşamasında tekrar düşünülebilir (otomatik cüzdan takibi fikri iyiydi).
- **"Küçük coinlerde alıcı eşiği 8"**: gölgelerde FDV yeni kaydediliyor, veri yok (1 sinyal).
- **ÇIK sinyali ↔ bildirim eşleşmesi** `/strateji`'de 0 çıktı (başlangıç fiyatı eksikliği şüphesi, yedek fiyat
  eklendi; yeni veride tekrar bakılmalı). ÇIK'ın kendi karnesi iyi (10 sinyal: yarısı 1s sonra daha aşağıda,
  kaçırılan 1.5x yok).
- Rug'ı kazananları kaybetmeden düşürmek zor (rug ~%10 sabit); odak kazananları yakalamak.
- V3/V4 honeypot simülasyonu yapılmadı (Fomo'daki başarılı satışlar yeterli kanıt; karne sorun göstermiyor).

## Sıradaki işler (öncelik sırası)
1. **Canlı doğrulama (30 Eylül hatırlatması bu eski sohbete gelir; yeni sohbette kullanıcıdan çıktıları iste)**:
   `/karne 72` (⚡ Erken bildirimler grubu: kalıcı 5x ~%45 tutuyor mu; bildirim gidenler kalıcı 5x ~%22+),
   `/geritest`, `/kazananlar`. Erken kural canlıda kötüyse `/erken 90` veya kapat; iyiyse 80'i dene.
0. **⚡ Erken odak (1 Ekim)**: `/mod erken` + `/hedef 168` çıktısıyla en iyi çıkış kuralını seç; sonra erken kuralın
   parametrelerini (son 5 dk alıcı, alıcı başına $, tutma, momentum) $ sonucuna göre optimize et — eski/yeni yarı
   ayrımıyla, aşırı uydurmaya dikkat (canlı erken sinyal az). Gölge kural A sinyalleri veri büyütür.
1b. **ÇIK sinyalini düzeltmek** (kullanıcı: öncelikli değil): hangi ÇIK nedeni (dev/balina/kim satıyor) tutuyor, `/karne`'de nedene göre kırılım.
2. **İkinci dalga bildirimi**: wave2 grubu karnede iyi çıkarsa (momentum kırılımıyla) bildirimi aç (ROBINPEPE gibi
   saatler içinde büyüyenler için).
3. **Erken kural B ve alıcı eşiği**: veri birikince `/geritest` sonundaki B ve "alıcı eşiği 8" bölümleri.
4. **Kazanan otopsisini büyütmek**: 8 kazanan az; `/kazananlar 7 5` (5x+) ile daha fazla örnek; "❓ görülmedi"
   çoksa kapsam sorunu (Fomo dışı coinler).
5. **Momentum v2 ağırlıklarını yeniden gözden geçirme** kalıcı 5x ile (`/analiz` + `/sinyal` ile kazananların ortak
   özellikleri). Yaş düzeltmesi sonrası v2 dağılımı değişti; `/tarama`'yı birkaç gün sonra tekrar çalıştır.
6. **Tepki süresi gerçekçiliği**: simülasyonlara "bildirimden 2-3 dk sonra giriş" varsayımı.
7. **Piyasa rejimi**: `/analiz`'de `market_buyers_1h` dilimlerine bak; fark varsa eşikleri rejime göre değiştir.
8. Sonraki aşama (kullanıcı onayıyla): pozisyon büyüklüğü/risk yönetimi (sinyal güvenine göre $20–$100),
   gerçek işlem takibi, Twitter/X verisi (ücretli, önce fiyat sorulur), Solana (ayrı proje).
