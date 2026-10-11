# Solana kârlı cüzdan araştırması — devir notu

Bu proje claude.ai'de başlayan bir sohbetten Claude Code'a taşındı (10–11 Ekim 2026).
Kullanıcıyla Türkçe konuş. Kullanıcı işleri elle yapmak istemiyor; mümkün olan her şeyi
otomatikleştir. Sadece kaynağıyla doğrulanabilir rakam kullan, emin değilsen sor.

## Amaç
Solana'da (çoğunlukla pump.fun memecoin) tutarlı kâr eden, yeni tokenlere erken girip
kârla çıkan veya "insider" olabilecek cüzdanları bulmak, takip etmek ve kopyalamaya değer
olup olmadığını **gerçek para koymadan** test etmek. Kullanıcının ayrıca VPS'te çalışan,
Telegram onaylı bir kripto trading botu var (merkezi borsa spot); bu proje ondan ayrı.

## Veri kaynakları
- **Helius** (ücretsiz plan: ayda 1M kredi, 10 istek/sn). Anahtar `.env` içinde `HELIUS_API_KEY`.
  En çok işe yarayan çağrı `getTransactionsForAddress` (Helius'a özel): `sortOrder: asc/desc`,
  `filters: {blockTime: {gte/lte}}`, `transactionDetails: full`, `maxSupportedTransactionVersion: 1`
  (0 verirsen hata alırsın). Websocket `logsSubscribe` (mentions) çalışıyor.
  ~4.200 çağrı ≈ 26 bin kredi ölçüldü (çağrı başına ~6 kredi).
- **DexScreener** (anahtarsız): `/tokens/v1/solana/{30 adrese kadar}`, `/latest/dex/search`,
  `/token-boosts/*`, `/token-profiles/latest/v1`. Python urllib ile `User-Agent` başlığı şart, yoksa 403.
- **Bitquery MCP**: deneme planının kotası doldu, kullanılamıyor. (Kota dolunca "missing required
  resultType" hatası veriyor; protokol hatası sanıldı, değil.)
- Genel Solana RPC getTransaction'ı ~4-5 sn'de bir veriyor, tarama için işe yaramaz.

## Klasörler
- `paper_copy/` — **kâğıt üstünde kopyalama servisi** (asıl teslimat). 15 cüzdanı websocket ile
  dinler, alımda 30 sn ve 2 dk gecikmeli sanal pozisyon açar, cüzdan %50 satınca çıkar, Telegram'a
  bildirir, 21:00'de günlük rapor. Gerçek işlem yapmaz. Kurulum: `paper_copy/KURULUM.md`.
  Henüz VPS'e KURULMADI ve Telegram kısmı gerçek token ile test edilmedi.
- `research/` — tarama kodları ve önbellek veriler:
  - `hl.py` Helius istemcisi (hız sınırlı) · `early.py` tokenlerin ilk 30 dk alıcıları
  - `freq.py` cüzdan işlem sıklığı (bot eleme) · `pnl.py` cüzdan bazında SOL cinsinden gerçekleşmiş kâr
  - `select.py` tutarlılık süzgeci + aynı anda işlem yapan kümeleri birleştirme
  - `backtest.py` gecikmeli kopyalama testi · `flags.py`/`verify.py` insider işaretleri, fon zinciri
  - `discover2.py` profilli cüzdanların tokenlerinden yeni kazananları bulma
  - `early/`, `pnl/`, `ev/` önbellek (tekrar çağrı harcamamak için; dosya varsa yeniden çekilmez)
  - `winners.txt`, `winners2.txt` incelenen 24 kazanan token · `selected.json` süzgeçten geçen 27 operatör
  - `backtest_round1.json`, `backtest2.json` kopyalama testleri
- `sonuclar/izleme_listesi.csv` — 39 cüzdanlık liste, her satırda kâr, kazanma oranı, kopya testi.

## Bulgular (özet)
1. Birden fazla kazanan tokene erken giren cüzdanların neredeyse hepsi bot (günde 50–2.500 token), çoğu zararda.
2. **Küme A**: 6 cüzdan (`6yjt4N…`, `GiBSJd…`, `3ZmfqV…`, `Guh1fc…`, `wYFUpd…`, `CduW4f…`) aynı 74 tokeni
   5 sn arayla almış; fonlama 2 ara cüzdanla gizlenmiş, ikisinin kök fonlayıcısı ortak. ~1.361 SOL kâr. Tek operatör.
   İkinci bir 7 cüzdanlık küme de var (`4TPGrGEt…`, üyeleri `selected.json` içinde).
3. 5 cüzdanın ortak fonlayıcısı (`5tzFkiKs…`) borsa hot wallet çıktı → anlamsız sinyal, elendi.
4. **Kopyalama çalışmıyor**: 25 tutarlı cüzdanın kendi medyanı +%5,2 (%56 kazanan); 30 sn / 2 dk gecikmeyle
   kopyalayınca medyan −%3, %30 kazanan, en iyi 3 işlem hariç ortalama −%2/−%4. Kâr hızdan geliyor
   (çoğu pozisyonu <1 dk tutuyor). Tek pozitif aday `J4d9GkjMeujQJMwZZYX9wq84FARy5GXE5G2cRo2j45zn`
   (30 sn +%9, 2 dk +%6 medyan) ama n=14–17, şans olabilir.
5. Seçim yanlılığı: cüzdanlar aynı 30 günlük dönemde kârlı oldukları için seçildi; ileriye dönük performans daha kötü olabilir.

## Bilinen sınırlamalar
- Kâr hesabı sadece SOL/wSOL karşılığı swap'ları kapsar; USDC ile yapılanlar ve pencereden önce alınanlar hariç.
- `pnl.py` cüzdan başına en fazla 400 işleme bakar (MAX_PAGES=4); yoğun cüzdanlarda 30 günün tamamı değil.
- Gecikmeli fiyatta 60 sn içinde işlem yoksa test o işlemi atlar (sığ likidite → gerçek kayma daha kötü olabilir).
- Bir tokende fiyat verisi hatası saçma getiri üretti; >20x getiriler şüpheli sayılıyor.
- Adres yazarken asla kısaltmadan tahmin etme; her zaman veriden programatik al (bir kez bu hata yapıldı, düzeltildi).

## Sıradaki adımlar
1. `paper_copy` servisini kullanıcının VPS'ine kur (KURULUM.md), `test-tg` ile Telegram'ı doğrula, systemd ile sürekli çalıştır.
2. 2–3 hafta sonra günlük rapordaki +120 sn satırına bak; pozitif değilse gerçek parayla kopyalama yok.
3. İsteğe bağlı: tarama otomatik ve haftalık yapılsın (yeni kazanan tokenler → erken alıcılar → süzgeç → backtest),
   iyi çıkan yeni adaylar `paper_copy/wallets.txt`'e eklensin.
