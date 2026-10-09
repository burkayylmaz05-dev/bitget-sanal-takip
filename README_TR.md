# Bitget BTC/ETH sanal takip — ücretsiz GitHub Actions

**Sadece fiyat ve sinyal izleme; gerçek alım-satım emirleri YOKTUR.**

Depo: `burkayylmaz05-dev/bitget-sanal-takip`.

## Kurulum tamamlanma durumu

ChatGPT tarafından kod ve zamanlanmış GitHub Actions iş akışı yüklenmiştir. **Sanal test Telegram anahtarı olmadan da başlar.** Telefona mesaj almak istersen **hesap sahibi** Actions Secrets altına aşağıdaki iki değeri bir defa eklemelidir. Değerleri **sohbette paylaşma**, dosyaya yazma, README'ye yapıştırma:

1. GitHub → bu depo → Settings → Secrets and variables → Actions → New repository secret
2. `TELEGRAM_BOT_TOKEN`: mevcut Telegram botu gizli anahtarı
3. `TELEGRAM_CHAT_ID`: kendi sohbet kimliğin

İstersen GitHub → Actions → **Bitget BTC ETH Sanal Takip (ucretsiz)** → Run workflow ile ilk çalıştırmayı beklemeden başlatabilirsin. Zamanlanmış çalıştırma da kendi kendine başlayacaktır.

## İçerik

- `bitget_sinyal_takip.py`: mevcut v3 BTC A/B sanal izlemesi ve v2 BTC/ETH sinyal mantığı
- `github_runner.py`: tek çalıştırmalık GitHub Actions adaptörü
- `github_notify.py`: kayıt commit edildikten sonra Telegram'a kuyruk gönderimi
- `.github/workflows/bitget.yml`: yaklaşık her 5 dakikada bir kontrol
- `tests/test_safety.py`: çevrimdışı güvenlik testleri

Her A/B stratejisi 1.000 USDT sanal bakiye ile başlar. Kullanılan komisyon, kayma ve funding değerleri **tahminidir**. Herhangi bir Bitget API anahtarı, Bitget özel uç noktası veya emir gönderme işlevi kullanılmaz. Sonuçlar gerçek borsa PnL'i değildir.

## Sınırlamalar

- GitHub Actions zamanlanmış işler gecikebilir veya atlanabilir; **kesintisiz 7/24 ve tam beş dakika garantisi yoktur.**
- Public depoda tüm kod ve sanal işlem günlükleri görülebilir; Telegram Secrets değerleri görülemez.
- Sanal izleme, Secrets olmadan çalışır ve açık depo içinde kayıt yapar. Secrets olmadan **yalnızca Telegram bildirimleri gönderilmez**.
- İşlem günlüğü açık depoda tutulacağı için kişisel veri / özel anahtar konmamalıdır.
- GitHub Actions 60 gün etkin olmayan açık depolardaki schedule tetikleyicilerini devre dışı bırakabilir.
- V2 ve V3 raporları ayrı tutulur. Bilgisayarda aynı Telegram botunu aynı anda çalıştırmak çift bildirim üretebilir.
- Gerçek Bitget API bağlantısı ve Telegram iletimi ancak GitHub Actions çalışması sırasında doğrulanabilir.

GitHub Actions billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
