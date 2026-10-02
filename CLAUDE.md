# Proje notu (yeni sohbetler için — önce bunu oku)

Fomo uygulamasında (fomo.family) işlem gören Robinhood Chain coinlerini tarayan, güven taraması yapıp Telegram'dan
bildirim gönderen bot + yükselecek coinleri erken bulma araştırması. Proje özeti: **`PROJE.md`**, bot anlatımı:
`README.md`, kod: `rhscanner/`, araştırma: `scripts/`.

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

## Proje durumu → `PROJE.md`
**Önce `PROJE.md`'yi oku**: amaç, botun şu anki hali, kanıtlanmış bulgular, denenip bırakılanlar, ölçüm kuralları,
betiklerin durumu ve yol haritası orada (tek özet; bu dosyada tekrarlanmaz). Her önemli bulgu/karar sonrası
`PROJE.md` güncellenir.
Kısaca (2 Ekim): hedef yeni coinlerde güvenli olanları ve ciddi yükselecekleri erken yakalamak. Güven taraması hazır.
Yükseliş için en iyi aday: "Fomo 3. alıcısında tarama (en iyi %10) + 1 saat tut" (kayan pencerede, dürüst çıkış
seçimiyle +$50/işlem; kârı ~%5 büyük kazanan getiriyor). Sıradaki: bota bildirimsiz kayıt modu.
Kullanıcı kararları: sadece ücretsiz kaynak (X API yok), Fomo "thesis" yazıları kullanılmaz, karar sadece zincir verisiyle.

## Araştırmada uyulacak ölçüm kuralları (her biri bir kez sahte kâr üretti; ayrıntı `PROJE.md` §5)
Gelecek bilgisi yok (havuz derinliği dahil) · giriş gelecekteki bir işleme bağlanmaz · "ileride Fomo'ya gelen coinler"
gibi evren seçimi yok · yol sırası (stop hedeften önce geldiyse stop) · düşüş/çıkış fiyatı tüm işlemlerden (sadece alım değil), ölü coin yarı fiyat · yükseliş iki
ardışık alımla, coin başı tavan 100x · Fomo komisyonu en az $0.95 + kayma · ayrı test dönemi / kayan pencere, "en
iyi %1 hariç" kontrolü. Sonuç fazla iyiyse önce hata ara.

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

## Mimari (dosyalar)
`bot.py` Telegram + akış (Fomo'da 10 dk'da `/minalici` alıcı ve `/minhacim` $ → güven taraması → skor ≥ `/minskor`
ise bildirim) · `fomo.py` Fomo işlemleri · `analyzer.py`/`checks/`/`scoring.py` güven skoru (Fomo churn = sahte
hacim bulgusu, bot'un tracker'ından `fomo["churn_share_30m"]` ile) · `launches.py` Pons lansman indeksi
(geliştirici geçmişi) · `hooks.py` V4 hook kaydı · `report.py` güven raporu metni · `flow.py` akış özellikleri
(araştırma; ileride canlı kural). Sunucudaki DB'de eski `signals` tablosu duruyor, artık yazılmıyor/okunmuyor.
Araştırma betikleri `scripts/` — hangisinin güncel/eski olduğu ve çalışma sırası `PROJE.md` §6'da.

## Telegram komutları (hepsi bot.py HELP'te)
`/check <adres>` `/trend` `/minskor` `/minalici` `/minhacim` `/durdur` `/devam` `/durum`

## Veri (araştırma)
**Veri arşivi: GitHub `veri` dalı** (gün başına parquet ~9 MB, `supply.parquet`; 1-3 Eylül + 17 Eylül-1 Ekim; 3-17 Eylül
eksik, indirilmeyecek — kullanıcı kararı). Yeni oturumda: `git fetch origin veri && git worktree add /tmp/veri
origin/veri` → `python scripts/data_import.py /tmp/veri fomo.db` (~1 dk) → `fomo_supply.py fomo.db` (eksik arzlar) → `pons_launches.py fomo.db`.
Yeni günler: `fomo_download.py` → `data_export.py fomo.db /tmp/veri` + commit/push (veri dalına). RPC'ye `user-agent`
başlığı gerekir. Fomo olaylarında satış $'ı yok → USDG Transfer(to=executor) ile eşleniyor; Fomo toplu tx'lerinde
~%5 satış fiyatı bozuk → yükseliş için ALIM'ları kullan (düşüş için tüm işlemler, `PROJE.md` §5). Araştırma venv'i: `numpy pandas pyarrow scikit-learn`.

