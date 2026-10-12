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

## DURUM (12 Ekim): PROJE DURDURULDU
Kullanıcıyla birlikte karar verildi: cüzdan kopyalama yolu kâr getirmiyor (bulgular aşağıda). Servis
hiçbir yerde çalışmıyor, sunucuya kurulmadı. İleride dönülürse önce aşağıdaki bulguları oku; aynı testleri
tekrarlamak yerine yeni bir fikirle başla. Helius anahtarı sohbette paylaşıldı, kullanıcıya yenilemesi önerildi.

## 12 Ekim oturumu: research/v2 (bias'sız yeniden tarama) — ÖNCE BUNU OKU
Kod `research/v2/`, önbellek repoda (`trades/` 3.700+ cüzdanın 21 günlük ham swap'ları, `prices.json`,
`launch.json`, `pricepath2/`, `copysim*/`). Yeni oturum kredi harcamadan devam edebilir.
- `trades.py` ham swap listesi (bot/yoğun erken eleme) · `metrics.py` token kârı: satılmayan güncel fiyattan
  (likidite < 5k$ → 0, değer likiditenin %10'u ile sınırlı), maliyeti < 0.01 SOL olan token hariç
- `analyze2.py`/`robust.py` kalıcılık testi: havuz = 30 Eyl öncesi kazananların erken alıcıları (kâra bakılmadan),
  seçim 21 Eyl–2 Eki, test 2–12 Eki, havuz tokenleri testten hariç
- `launch.py`/`entry.py` token oluşturma anı ve yaratıcısı · `copysim.py` havuz rezervinden fiyatla (ücret/bahşişten
  bağımsız) +1/3/10 sn anlık kopya simülasyonu · `consensus.py` ortak alım sinyali · `swing_*`, `midbuyers.py` uzun tutanlar

### Bulgular
1. **Kârlılık kalıcı**: eğitimde getirisi en iyi %5 → testte %81 kârlı, +%31 (sadece gerçekleşen +%24, en iyi token
   hariç +%15); alt %50 → %13 kârlı, −%6. Önceki "kârlı" listeler aynı dönemle seçilip ölçüldüğü için şişkindi.
2. **Ama kopyalanamıyor**: en kârlıların bir kısmı token yaratıcısı (ör. 7naFFwuE 220 tokenin 146'sını kendisi
   çıkarmış), bir kısmı açılış bloğu snipe'çısı; geri kalan hızlı işlemciler zaten başka botlarca kopyalanıyor
   (alımdan sonraki aynı saniyede fiyat %20–80 sıçrıyor, satışta çöküyor).
3. **Anlık kopya simülasyonu** (101 cüzdan, 1.100 işlem): +1 sn medyan −%19, kazanma %26; ortalama +%11 ama en iyi
   5 işlem çıkınca negatif. Alım sonrası 1 sn sıçraması >%10 olan cüzdanlarda kopya −%15/−%29.
4. **Uzun tutanlar** (24 yerleşik memecoinin 822 orta dönem alıcısı): eğitim kârı testte devam etmiyor (−%0,3).
5. **Ortak alım sinyali** (k yetenekli operatör 10 dk içinde aynı token): kontrol grubundan farksız; 5 dk medyan −%35.
6. Fiyatı işlem yapanın SOL değişiminden hesaplamak yanıltıcı (ücret+Jito bahşişi: alımda ~+%3, satışta −%4/−%7);
   havuz rezerv değişimini kullan (`copysim.pool_price`). Yoğun tokenlerde ilk 100+ işlem başarısız arbitraj olabilir.
7. Bitquery bu oturumda da kota hatası verdi. ~45 bin Helius çağrısı yapıldı (kredi karşılığı ölçülmedi).

### paper_copy (12 Ekim güncellemesi)
Havuz fiyatı, gecikmeler 1/3/30 sn, yeni 10 cüzdanlık liste (copysim'de en iyi işlem hariç ortalaması pozitif ve
az kopyalanan). Eski sonuçlar `paper_eski_12ekim.db` / `rapor_eski_12ekim.txt`. Bulut konteyneri yeniden başlayınca
servis durur → 2–3 haftalık test için sunucu gerekli.

## Sıradaki adımlar
1. `paper_copy`'yi sunucuya kur; günlük raporda **+1sn** satırı 2–3 hafta pozitif değilse kopya fikri biter.
2. Kopya dışı fikirler (araştırılmadı): yoğun kopyalanan cüzdanların arkasındaki kopya dalgasını sinyal olarak
   kullanmak (lider alınca değil, dalga bitince ters yönde), yaratıcı/dev-dump cüzdanlarından kaçınma filtresi.
