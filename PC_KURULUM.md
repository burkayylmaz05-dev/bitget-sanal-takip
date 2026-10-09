# Bitget BTC/ETH bilgisayarda canlı sinyal takibi

**Ücretsiz.** Bilgisayar açıkken çalışır. Sadece halka açık Bitget verilerini kullanır, **gerçek emir göndermez**. GitHub Actions üzerindeki eski sanal testleri değiştirmez.

## Başlatma (Windows)

1. [PC_BASLAT.bat](https://raw.githubusercontent.com/burkayylmaz05-dev/bitget-sanal-takip/main/PC_BASLAT.bat) dosyasını bilgisayara kaydedin. İndirme sırasında uzantı `.bat` olarak kalmalı (`.txt` olmamalı).
2. Dosyaya çift tıklayın. Python 3 zaten yüklüyse, gereken tek ücretsiz `websocket-client` kütüphanesini yükler. Ardından aynı GitHub deposundan canlı bot ve mevcut sinyal motorunu indirir/günceller.
3. İlk çalıştırmada Telegram BotFather **token** ve **Chat ID** sorulur. Sadece kendi bilgisayarınızda girin. GitHub Secrets değerleri bilgisayara kendiliğinden aktarılmaz. Bunları sohbet ortamına ya da depoya göndermeyin.
4. Telegram'daki kendi botunuzla sohbeti Start / Başlat yapmış olmalısınız. Başlangıçta bir deneme bildirimi gelir. BTC/ETH fiyatları 30 saniyede bir ekranda görünür; fiyat akışı arka planda anlıktır. Sinyal sadece 5 dakikalık mum kapanıp analiz filtrelerinden geçtiğinde gönderilir.
5. Durdurmak için konsolda **Ctrl+C**. Bilgisayar uyku modunda veya kapalıyken takip yoktur.

## Sinyal yöntemi

Mevcut `bitget_sinyal_takip.py` içindeki EMA trend (5m/15m/1H/4H), RSI, MACD, hacim, kırılım, volatilite ve stop filtresi kullanılır. Ticker mesajları Bitget **public WebSocket** üzerinden piyasa değiştikçe gelir; sunucu sürekli her saniye veri göndermeyebilir. Mum analizleri 5 dakikalık kapanışlardan yaklaşık 5 saniye sonra yapılır. Bağlantı koparsa bot tekrar bağlanmayı dener. Aynı mum için çift alarm ve gecikmiş mum için tarihî alarm engellenir.

- Telegram bilgileri yalnızca `pc_telegram_ayar.json` yerel dosyasında saklanır. Dosyayı paylaşmayın.
- Sinyal işleme durumu `pc_canli_durum.json` dosyasında saklanır.
- Gerçek kârlılık doğrulanmadı; stop/hedef tahmindir, 10x kaldıraçta zarar hızla büyüyebilir.
- GitHub Actions workflow da açık ise Telegram'da farklı sistemlerden iki tür bildirim gelebilir. İsterseniz eski workflow'u daha sonra durdurabilirsiniz.
- Kaynaklar: https://www.bitget.com/docs/classic/rest-api ve https://www.bitget.com/api-doc/classic/contract/websocket/public/Tickers-Channel.
