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
- Branch: `claude/fomo-coin-scanner-app-mhz9rk` = **asıl proje dalı** (sunucunun `install.sh`'ı bunu kurar). Oturum başka
  bir branch atarsa (`ccr-...` / `claude/...`) ikisine de push et (kullanıcı izin verdi), ikisi aynı kalsın. PR açma
  (kullanıcı istemedikçe). Diğer dallar (`PROJE.md` §6): `veri` = veri arşivi (kalmalı), `main` = GitHub'ın boş ilk
  dalı (kullanılmıyor), eski oturum dalları = asıl dalda olmayan bir şey içermeyen kopyalar (kullanıcı "kalsın" dedi).
  Yeni oturumda dal sorulursa bunu açıkla.
- **Push'tan önce testler mutlaka geçmeli** (`python -m pytest -q`; komut zincirinde sonucu kontrol et).
- Telegram mesajları HTML: metinde çıplak `<` olursa Telegram mesajı reddeder ve komut sessizce cevapsız kalır
  → `escape()` / `&lt;` kullan; `tests/test_telegram_html.py` bütün rapor biçimlerini bu yüzden kontrol ediyor.

## Proje durumu → `PROJE.md`
**Önce `PROJE.md`'yi oku**: amaç, botun şu anki hali, kanıtlanmış bulgular, denenip bırakılanlar, ölçüm kuralları,
betiklerin durumu ve yol haritası orada (tek özet; bu dosyada tekrarlanmaz). Her önemli bulgu/karar sonrası
`PROJE.md` güncellenir.
Kısaca (2 Ekim, yeniden hizalama): bot yeni Fomo coinlerinden **yükselme ihtimali en yüksekleri** bulur, güvenlik
taramasını geçemeyenleri sessizce eler, kalanları **güven puanı + 2x ihtimali (nedenleriyle)** olarak bildirir; coin
bildirim fiyatının **brüt 2x**'ine ulaşınca "2x oldu" der. Alım-satım kararı kullanıcının; bot işlem yapmaz.
**Adım adım ilerlenir, her adım sonunda kullanıcıyla durulur** (`PROJE.md` §2): 0 temizlik · 1 güvenlik kriterleri ·
2 yükseliş kriterleri (backtest) · 3 simülasyon (karar kapısı) · 4 bot · 5 canlı izleme. Adımı atlama, hızlıca sonuca
koşma; kriterler kesinleşmeden bota dokunma. **Kapsam şimdilik sadece Robinhood Chain**; Fomo'nun diğer zincirleri
(Solana/pump.fun, BNB, Base) 6. adım — kullanıcı istedi: **her adım sonunda bunu hatırlat** (kısıtlı havuza bakıyoruz). "Bot alıp 1 saat tutar" / $ kâr / kayma araştırması hedef dışıydı, bırakıldı.
Kullanıcı kararları: sadece ücretsiz kaynak (X API yok), Fomo "thesis" yazıları kullanılmaz, karar sadece zincir verisiyle.

## Araştırmada uyulacak ölçüm kuralları (her biri bir kez sahte sonuç üretti; ayrıntı `PROJE.md` §6)
Gelecek bilgisi yok · bildirim fiyatı o anda bilinen son alım fiyatı (gelecekteki işleme bağlanmaz; son 3 alımın ortancası 2x'i şişirir) · "ileride Fomo'ya gelen
coinler" gibi evren seçimi yok · 2x iki ardışık alımla, coin başı tavan 100x · düşüş/son değer tüm işlemlerden, ölü coin
yarı fiyat · yol sırası · süresiz 2x'te veri sonunda yeterince izlenmeyen coin "olmadı" sayılmaz · kayan pencere, gün
gün, "en iyi %1 hariç" kontrolü · boş/dolu veri gelecekteki bir koşula bağlı olmasın (arz sadece "20+ işlemli" coinlerde = sızıntı) · başarı brüt (komisyon/kayma sadece 3. adımda, kararlaştırılırsa). Sonuç fazla iyiyse
önce hata ara.

## Sunucu
- Oracle Always Free, VM.Standard.E2.1.Micro, Ubuntu 24.04, IP `79.76.124.29`, kullanıcı `ubuntu`.
- Cloud Shell'den bağlantı: `ssh -i ~/.ssh/fomo ubuntu@79.76.124.29`
- Yapıştırma bozulmasın diye önce: `bind 'set enable-bracketed-paste off'`
- Güncelleme: `bash ~/Coin/deploy/install.sh` (systemd servisi `rhscanner`, DB `~/Coin/rhscanner.db`)
- İkinci servis `fomosol` = pump.fun/Solana veri toplayıcı (`rhscanner/solana.py` → `~/Coin/solana.db`); log:
  `journalctl -u fomosol -n 20 --no-pager`.
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
  bozuksa temiz venv kur (`python -m venv ...; pip install -r requirements-dev.txt`). ~64 test.
- CLI: `python -m rhscanner check <adres>`, `trend`.
- Kontratlar: `contracts/`, derleme `scripts/compile_contracts.mjs` (solc 0.8.26, viaIR).

## Mimari (dosyalar)
`bot.py` Telegram + akış (Fomo'da 10 dk'da `/minalici` alıcı ve `/minhacim` $ → güven taraması → skor ≥ `/minskor`
ise bildirim) · `fomo.py` Fomo işlemleri · `analyzer.py`/`checks/`/`scoring.py` güven skoru (Fomo churn = sahte
hacim bulgusu, bot'un tracker'ından `fomo["churn_share_30m"]` ile) · `launches.py` Pons lansman indeksi
(geliştirici geçmişi) · `paper.py` + `paper_model.json` + `paper_book.json` kâğıt test (5. alıcıda
puan, en iyi %2'ye sanal işlem, `/karne`; tablolar `paper_log`, `paper_book`, `paper_pending`, `scan_known`; model
`scripts/paper_export.py` ile) · `live.py` gerçek bildirim (`/canli`, kapalı; satılamama elemesi V4SellProbe ile,
güven puanı `trust_model.json`, 2x ve likidite takibi; tablo `live_log`) · `hooks.py` V4 hook kaydı · `report.py` güven raporu metni · `solana.py` Fomo Solana işlem toplayıcı (pump.fun curve + PumpSwap, websocket) · `flow.py` akış özellikleri
(araştırma; ileride canlı kural). Sunucudaki DB'de eski `signals` tablosu duruyor, artık yazılmıyor/okunmuyor.
Araştırma betikleri `scripts/` — listesi `PROJE.md` §7'de.

## Telegram komutları (hepsi bot.py HELP'te)
`/check <adres>` `/trend` `/minskor` `/minalici` `/minhacim` `/durdur` `/devam` `/durum` `/karne [saat]` `/kagitbildirim ac|kapat` `/canli ac|kapat`

## Veri (araştırma)
**Veri arşivi: GitHub `veri` dalı** (gün başına parquet ~9 MB, `supply.parquet`; 1-3 Eylül + 17 Eylül'den bugüne; 3-17 Eylül
eksik, indirilmeyecek — kullanıcı kararı). Yeni oturumda: `git fetch origin veri && git worktree add /tmp/veri
origin/veri` → `python scripts/data_import.py /tmp/veri fomo.db` (~1 dk) → `fomo_supply.py fomo.db` (eksik arzlar) → `pons_launches.py fomo.db`.
Yeni günler: `fomo_download.py <gün> yeni.db` → `data_merge.py yeni.db fomo.db` → `data_export.py fomo.db /tmp/veri` + commit/push (veri dalına). RPC'ye `user-agent`
başlığı gerekir. Fomo olaylarında satış $'ı yok → USDG Transfer(to=executor) ile eşleniyor; Fomo toplu tx'lerinde
~%5 satış fiyatı bozuk → yükseliş için ALIM'ları kullan (düşüş için tüm işlemler, `PROJE.md` §6). Araştırma venv'i: `numpy pandas pyarrow scikit-learn`.

