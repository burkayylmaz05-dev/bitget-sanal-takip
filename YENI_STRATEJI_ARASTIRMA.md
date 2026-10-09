# Bitget BTC/ETH — yeni kârlı strateji arayışı (9 Ekim 2026)

**Sonuç: 7 alternatif LONG/SHORT stratejisi ve 3 funding carry stratejisi inceledik. Henüz masraf sonrası güvenilir, tekrar edilebilir kârı kanıtlanan bir sistem yok. Gerçek para işlemi başlatmayın.**

## A. Yön bazlı stratejiler (240 günlük veri)

- Veriler BTCUSDT ve ETHUSDT Bitget USDT-FUTURES. Her birinde 5dk 69.120, 15dk 23.040, 1s 5.760, 4s 1.440 gerçek kapanmış mum.
- Sinyal çeşitleri: 1 saat Donchian kanal 20/55, 1 saat EMA20 geri çekilme, 1 saat Bollinger dönüş, 4 saat Donchian kırılımı, 4 saat EMA trendi, 15dk trendle dönüş.
- 50 gün gösterge ısınması; 100 gün geliştirme; son 90 gün bağımsız doğrulama. Farklı stratejiler birbirinden ayrı 1.000 USDT sanal hesapta.
- Komisyon her tarafta %0,06; tahmini fiyat kayması her tarafta %0,03; stop ilk mumda da işler; stop/hedef aynı mumda görünürse stop önce; pozisyon nominal büyüklüğü en fazla 1x; işlem başına hedef risk %0,5.
- **Önemli eksik: gerçek funding, derinlik, spread değişkenliği, gerçek emir gecikmesi ve likidasyon modellenmedi.**

| Kombinasyon | Geliştirme (100g) | Doğrulama (90g) | Doğrulama kapalı işlem |
|---|---:|---:|---:|
| BTC 1s kanal 20 | -%5,368 | -%4,126 | 29 |
| BTC 1s kanal 55 | -%0,909 | -%1,498 | 8 |
| BTC 1s EMA20 geri çekilme | -%5,947 | -%6,912 | 40 |
| BTC 1s Bollinger dönüş | -%4,595 | -%4,443 | 28 |
| BTC 4s kanal kırılımı | +%0,331 | -%2,103 | 4 |
| BTC 4s EMA trend | +%1,500 | -%1,432 | 8 |
| BTC 15dk dönüş | -%16,912 | -%17,036 | 97 |
| ETH 1s kanal 20 | +%0,083 | +%0,355 | 30 |
| ETH 1s kanal 55 | +%0,100 | +%0,336 | 12 |
| ETH 1s EMA20 geri çekilme | -%3,760 | -%2,019 | 42 |
| ETH 1s Bollinger dönüş | +%0,203 | +%0,829 | **2** |
| ETH 4s kanal kırılımı | -%2,965 | -%1,308 | 9 |
| ETH 4s EMA trend | +%1,227 | -%0,871 | 10 |
| ETH 15dk dönüş | -%14,446 | -%23,231 | 148 |

**En umut verici aday bile çok zayıf:** ETH 1s Donchian20, iki dönemde az kâr, son dönemde profit factor **1,035**. Ek ücret veya kayma bu sonucu silebilir. Bollinger yalnızca 2 işlemlik doğrulama nedeniyle güvenilir değil.

[Detaylı JSON sonuçları](research_alternatives_report.json) · [Açık kaynak test algoritması](research_alternatives.py) · [Başarılı GitHub çalışma kaydı](https://github.com/burkayylmaz05-dev/bitget-sanal-takip/actions/runs/37950999461)

## B. Spot al + vadeli short funding carry (90 günlük gerçek funding geçmişi)

- Bitget funding API'nin erişilebilir kapsamı yalnızca yaklaşık 90 gün: 270 funding olayı, BTC ve ETH için 1 saatlik spot ve futures fiyatlarından **2.160'ar** mum kullanıldı.
- İlk 15 gün ön veri, sonra 37 gün geliştirme ve 38 gün doğrulama.
- 1.000 USDT başlangıç hesabında yaklaşık 500 USDT spot alış + 500 USDT nominal short perpetual, 1x teminat. İşlem masrafları spot %0,10 her tarafta, futures %0,06 her tarafta, her fiyat bacağı ve yönde tahmini %0,03 kayma.
- Tarihsel funding oranları gerçek, ödeme nominal tutarı tarihi 1 saatlik fiyatla yaklaşık hesaplandı. Fiyat farkı kâr/zararı ve ücretler dahil edildi; **mark-price, spot/perp likidite, gerçek emrin dolması, teminat aktarımı ve kesin likidasyon modelleri mevcut değil.**
- *Her dönemde işlem sayısı sadece bir* (14 günlük eşik stratejisinde hiç işlem yok); test öncü gözlemdir, istatistiksel geçerlilik yok.

| Sistem | İlk 37g | Son 38g | Açıklama |
|---|---:|---:|---|
| BTC sürekli hedge | +%0,021 | +%0,149 | Son dönem 1.000 USDT için +1,49 USDT |
| ETH sürekli hedge | +%0,053 | +%0,236 | Son dönem 1.000 USDT için +2,36 USDT |
| BTC 7 gün funding filtresi | -%0,084 | +%0,124 | İlk dönem negatif |
| ETH 7 gün funding filtresi | -%0,179 | +%0,223 | İlk dönem negatif |
| BTC/ETH 14 gün sıkı filtre | %0 | %0 | İşlem yok |

Fundinge dayalı sistem yön tahmin ihtiyacını azaltır ancak funding negatife dönebilir, iki bacaklı işlem zor ve küçük miktarda getirisi sınırlıdır. **Risksiz arbitraj değildir.**

[Carry özeti](research_carry_report.json) · [Full 90-gün rapor ZIP — GitHub Actions artifact](https://github.com/burkayylmaz05-dev/bitget-sanal-takip/actions/runs/37952600902/artifacts/11625929136) · [Hesaplama kodu](research_carry.py)

## Son karar / sonraki araştırma şartları

1. **Mevcut gerçek para/kaldıraçlı sinyaller için hiçbir strateji onaylı değil.** Sinyal botu sadece uyarı ve sanal izleme amacıyla kalsın.
2. ETH 1s Donchian20 yalnızca araştırmaya aday: en az 3 ay gerçek zamanlı forward-paper işlem günlüğü, kayma/ücret/funding sonrası gerçek performans.
3. Funding carry için daha uzun güvenilir funding verisi ve borsa teminat/basis/risk şartları gerekli; tek 38 günlük pozisyonun artıda olması kârlılık kanıtı değil.
4. Gelecekteki testte parametreleri son gördüğümüz verilere göre değiştirip aynı dönemde yeniden kazanç göstermek güvenilir ölçüm değildir (data snooping / overfit). Yeni ve daha sonra oluşacak mumlar ile kontrol edilmeli.

Bu araştırma yatırım danışmanlığı veya gelecekteki net getiri garantisi değildir.
