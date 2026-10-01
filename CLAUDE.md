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

## Sıradaki işler
1. **"2x'e eğilimli coin" araştırması (zincir verisi)**: her coin için her an (ör. dakikada bir) "bu fiyattan +30 sn
   sonra girseydim, sonradan (süre sınırı yok / birkaç gün) en az 2x gördüm mü (art arda iki alım), önce ne kadar
   düştü, ne kadar sürdü" etiketi + kayma. Hangi an/özelliklerde 2x olasılığı tabandan belirgin yüksek → sade kural,
   kayan pencere (gün gün) doğrulama. Güven skoru zincirden hesaplanamaz; kural güven filtresiyle birlikte çalışacak.
2. Bulunan kural bota "hızlı bildirim" olarak (flow.py) + Fomo fiyatlarıyla canlı ölçüm (önce bildirimsiz kayıt).
3. Sonraki aşama (kullanıcı onayıyla): pozisyon/risk, gerçek işlem takibi, Twitter/X (ücretli, önce fiyat sor), Solana.
