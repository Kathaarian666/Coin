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
   (rug %17). Birkaç gün sonra `/karne 72` + `/bulgular 72` ile tekrar bak.
2. **Twitter/X verisi** (opsiyonel): sadece karne verisi olduktan sonra ve ucuz bir 3. parti API ile
   (~$20/ay civarı); kullanıcıya fiyatla sorulacak.
3. **Mezuniyet öncesi Pons takibi** (opsiyonel): lansman indeksi hazır olduğu için yeni Pons coinlerini
   doğduğu anda (Fomo'da hacim gelmeden) izleme.
4. **V3/V4 honeypot simülasyonu** (şu an sadece V2; Fomo'da başarılı satışlar honeypot olmadığını gösteriyor).
5. **Solana** — ayrı proje olarak, Robinhood tarafı oturduktan sonra.
