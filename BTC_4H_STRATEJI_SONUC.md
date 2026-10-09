# BTC 4H EMA20 PULLBACK — kilitli tarihsel strateji raporu

**10 Ekim 2026. Bu rapor stratejinin geçmiş Bitget USDT vadeli OHLC verilerindeki sanal sonuçlarını gösterir. Gelecekte kâr garantisi değildir. Borsa emri otomatik açılmaz.**

## İncelenen strateji

- BTCUSDT **4 saatlik EMA20 geri çekilme**, 4H EMA50 ve günlük UTC EMA100/EMA200 trend filtresiyle LONG veya SHORT.
- Son kapanan 4H mum EMA20'yi trend yönünde yeniden kestiğinde sinyal; son **tamamlanmış** günlük verinin EMA100/EMA200 ve eğim koşulları aynı yönü göstermeli.
- Bir sonraki 4H mum açılışından sanal giriş. Başlangıç stopu 2x 4H ATR; sonrasında kapanış sonrası güncellenen 2,5x ATR trailing stop; azami 30 gün.
- Başlangıç sermayesi her dönemde ayrı **1.000 USDT**, pozisyon nominal büyüklüğü en fazla 1x; hedef stop riski işlem başına %0,5.
- Her tarafta %0,06 taker komisyonu, ayrıca her tarafta %0,03 olumsuz fiyat kayması.
- İkinci dayanıklılık testinde komisyon %0,12, kayma %0,06 her tarafta.
- Sinyalin oluştuğu kapanıştan **sonraki** açılışta işlem girer; giriş mumunda stopa değerse stop kayıp yazar, kapanıştan sonra yenilenen trailing stop bir sonraki mumda devreye girer.

## Aynı kurallarla 4 ayrı yaklaşık 230 günlük dönem

| Dönem UTC | Sanal işlem | Kazanan | Net getiri | 2x maliyetli net getiri | Profit factor | En büyük sanal düşüş |
|---|---:|---:|---:|---:|---:|---:|
| 17.07.2023–03.03.2024 | 18 | 7 | **+%6,948** | +%6,174 | 2,756 | -%2,251 |
| 03.03.2024–19.10.2024 | 15 | 7 | **+%2,531** | +%2,001 | 1,782 | -%1,926 |
| 06.07.2025–21.02.2026 | 25 | 7 | **+%2,005** | +%0,942 | 1,248 | -%6,483 |
| 21.02.2026–09.10.2026 | 16 | 5 | **+%2,576** | +%1,945 | 1,772 | -%2,730 |

**74 kapanan sanal işlem** ve **26 kazanan** bu dört tarihsel pencerede. Dönemler arasında 2024 Ekim–2025 Temmuz veri dışı 260 günlük gösterge ısınma boşluğu vardır; bu tabloyu kesintisiz bir portföy getiri serisi gibi birleştirmeyin. Her dönem 1.000 USDT'den bağımsız başlatıldı.

### Kısıtlar ve seçim yanlılığı

- 12 piyasa-strateji kombinasyonunun sonuçlarına bakıldıktan sonra **BTC PULLBACK_BIDIR** adayı öne çıktı; bu, çoklu karşılaştırma/veriye uyum riskini artırır.
- İlk iki eski veri dönemi seçilen kuralları hiç değiştirmeden ek dayanıklılık kontrolü olarak kullanıldı. Bu **gerçek ileriye dönük işlem** doğrulaması değildir.
- Modelde gerçek **funding ücretleri, değişken bid/ask spread, teminat/likidasyon mekanizması, bağlantı gecikmesi, kısmi dolum ve vergiler** yoktur. Canlı performans daha kötü olabilir.
- Son 230 günde pasif BTC 1x alış-tut stratejisi yaklaşık +%20,02 verirken, sinyal stratejisi +%2,576 getirdi. Yani bu dönemde pasif tutmayı yenmedi. Önceki dönemde BTC alış-tut -%37,28 iken model +%2,005 getirdi; farklı piyasa rejimlerinde maruziyeti azaltabildi.
- Sadece 16 işlem içeren son doğrulama dönemi istatistiksel kesinlik sağlamaz. Geçmiş dönemde olumlu olması ileride kazanç garantisi değildir.

## Kod ve kanıtlar

- 720-günlük 6-strateji karşılaştırmasının [test kodu](research_trend_v4.py) ve [GitHub koşu kaydı](https://github.com/burkayylmaz05-dev/bitget-sanal-takip/actions/runs/37993196558).
- Farklı eski 720 günlük veri üzerinde kilitli BTC kuralının [test kodu](research_trend_older.py) ve [GitHub koşu kaydı](https://github.com/burkayylmaz05-dev/bitget-sanal-takip/actions/runs/37993416354).
- Her iki koşunun orijinal JSON raporları GitHub Actions → Artifacts bölümünden indirilebilir; işlem istatistikleri raporlardan alındı.
- Yeni [PC BTC 4H aday alarm kodu](pc_btc_4h_alert.py): **yalnızca kamuya açık Bitget verisi okuyup Telegram'a aday sinyal bildirimi gönderir, gerçek borsa emri YOK.**
- [Canlı API dry-run smoke testi](https://github.com/burkayylmaz05-dev/bitget-sanal-takip/actions/runs/37993854633) gerçek BTC 4H ve 1Dutc geçmiş mumlarını okuyup kontrol etti; test anında yeni sinyal yoktu.

## Sonuç

Diğer test edilmiş yöntemlere göre daha olumlu ve tutarlı **araştırma adayı** BTC 4H EMA20 trend yönünde geri çekilme olmuştur. Ancak funding ve gerçek emir maliyetleri ölçülmeden, gerçek para ile otomatik alım-satım veya 10x kaldıraç kullanımı uygun değildir. Telegram bildirimleri aday işaretidir, işlem talimatı değildir.
