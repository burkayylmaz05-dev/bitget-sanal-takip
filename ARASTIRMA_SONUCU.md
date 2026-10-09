# BTC / ETH 5m–4H sinyal botu — tarihsel kârlılık denetimi

**Tarih: 9 Ekim 2026. SONUÇ: Kârlılık doğrulanamadı. Gerçek emir açmak için önerilmez.**

## Veri ve yöntem

- Kaynak: Bitget resmî **USDT-FUTURES** BTCUSDT / ETHUSDT, gerçek tarihsel OHLCV verileri. Spot/Binance verisi değildir.
- İncelenen 120 gün: 11 Haziran – 9 Ekim 2026 (UTC). Her sembolde 5m **34.560**, 15m **11.519**, 1H **2.879**, 4H **719** eksiksiz kapalı mum. Borsa API'sinden sayfalı indirme, zaman boşluğu kontrolü.
- İlk 40 gün gösterge hesaplarına ayrıldı. İlk ölçüm yaklaşık 48 gün: 21 Temmuz – 7 Eylül; doğrulama yaklaşık 32 gün: 7 Eylül – 9 Ekim.
- Mevcut `pc_zaman_dilimleri.py` EMA, RSI, MACD, ATR, hacim ve 20 mum kırılım filtreleriyle aynı strateji kuralları kullanıldı. Yüksek zaman dilimlerinde **yalnız o anda kapanmış** mumlar kullanılır.
- Mum kapandıktan sonra **sonraki 5 dakikalık mum açılışından** varsayımsal işleme girilir; hiçbir gerçek emir verilmedi.
- Standart taker komisyonu **her yönde %0,06**, olumsuz fiyat kayması **her yönde %0,03**. Stop ve hedef aynı 5m mumda görünürse **stop önce** sayıldı; **işleme giriş yapılan ilk mum da kontrol edildi**. Pozisyon başına hedef risk %0,5, nominal pozisyon en fazla 1x, bağımsız simülasyonda başlangıç sermayesi 1.000 USDT.
- Önemli eksikler: **Funding, değişken bid-ask spread, emir defteri derinliği, likidasyon, canlı emir gecikmeleri, gerçek hesap ücretleri ve tick bazlı fiyat yolu ölçülmedi**. Test gerçek kâr değil; bu varsayımlar bazı durumlarda iyimser kalabilir.
- Train/test sonuçları geçmişte tanımlı filtreler için yapılan bir tarihsel kontrol; bağımsız ileriye dönük piyasa testi değildir. Örneklem dışı dönem sınırlıdır.

## Son 32 günlük doğrulama (en önemli ölçüm)

| Sembol | Grafik | Kapanan işlem | Kazanan | Net kâr/zarar (1.000 USDT başına) | Profit factor |
|---|---|---:|---:|---:|---:|
| BTCUSDT | 5m | 23 | 8 | **−%2,089** | 0,547 |
| BTCUSDT | 15m | 12 | 1 | **−%2,493** | 0,267 |
| BTCUSDT | 1H | 6 | 4 | +%0,885 | 1,808 |
| BTCUSDT | 4H | 1 | 0 | −%0,198 | 0 |
| ETHUSDT | 5m | 31 | 7 | **−%5,120** | 0,365 |
| ETHUSDT | 15m | 17 | 5 | **−%1,931** | 0,579 |
| ETHUSDT | 1H | 4 | 1 | −%1,145 | 0,036 |
| ETHUSDT | 4H | 2 | 0 | −%0,390 | 0 |

**8 kombinasyonun 7'si zararda.** BTC 1H +%0,885 ama sadece **6** kapanan işleme dayandığı ve ilk dönemde zarar ettiği için güvenilir pozitif sonuç değildir.

## İlk yaklaşık 48 günlük dönem

| Sembol | Grafik | Kapanan işlem | Net kâr/zarar |
|---|---|---:|---:|
| BTCUSDT | 5m | 34 | −%1,856 |
| BTCUSDT | 15m | 18 | −%0,514 |
| BTCUSDT | 1H | 8 | −%1,644 |
| BTCUSDT | 4H | 1 | −%0,311 |
| ETHUSDT | 5m | 50 | −%6,028 |
| ETHUSDT | 15m | 36 | −%4,433 |
| ETHUSDT | 1H | 7 | +%0,111 |
| ETHUSDT | 4H | 3 | −%0,080 |

## Sonuç ve sınırlı kullanım

- **Canlı otomatik gerçek işlem YAPMA.** Telegram aday bildirimleri çalışabilir ama kârlı/kanıtlanmış değildir.
- BTC 1H tek başına seçilmemeli: 6 işlemle başarılı görünmesi tesadüf olabilir.
- Daha uzun dönemler, çoklu piyasa koşulları, walk-forward doğrulama, funding dahil etme ve ileriye dönük sanal takip gereklidir.
- Sinyalleri değiştirip aynı doğrulama döneminde tekrar tekrar optimize etmek kârlılığı kanıtlamaz (overfitting).

## Reprodüksiyon ve kaynaklar

- [Sonuçların tümü: research_backtest_report.json](research_backtest_report.json)
- [Geriye dönük test kaynak kodu: research_backtest.py](research_backtest.py)
- [Mevcut sinyal kuralları: pc_zaman_dilimleri.py](pc_zaman_dilimleri.py)
- [Bitget resmî historical-candles API](https://www.bitget.com/docs/catalog/classic-contract-market/classic-contract-market)
- [Bitget ücret bilgileri](https://www.bitget.com/en-CA/support/articles/12560603892734)
- [Deprez & Frömmel (2024), Out-of-sample teknik strateji araştırması](https://www.sciencedirect.com/science/article/pii/S1059056024003010)
- [Anghel (2022), İşlem maliyeti ve sahte keşif riski](https://www.sciencedirect.com/science/article/pii/S0165176522001720)
