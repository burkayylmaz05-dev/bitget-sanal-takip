# ETHUSDT 1H Donchian 20 — ileri sanal test

Amaç: 90 günlük tarihsel testte +%0,355, 30 kapanan işlem ve 1,035 profit factor veren (çok küçük, kârlılığı kanıtlanmamış) ETH 1 saatlik Donchian20 stratejisini gelecekteki piyasalarda sanal olarak doğrulamak.

## Windows kurulumu

1. GitHub ana klasöründeki PC_BASLAT.bat dosyasının yeni sürümünü eski PC_BASLAT.bat dosyasıyla değiştir.
2. Açık bot penceresini Ctrl+C ile kapat; yeni PC_BASLAT.bat dosyasına çift tıkla.
3. Sürüm 6 üç yeni Python dosyasını da indirir: research_backtest.py, research_alternatives.py, pc_eth_forward.py.
4. Telegram bilgileri mevcut yerel dosyadan okunur; kullanıcıdan tekrar istenmesi beklenmez.
5. Açılışta "ETH Donchian20 1H ileri sanal test aktif." ve sanal hesap özeti görünmeli.

## Risk ve yöntem

- Yalnızca Bitget kamuya açık USDT vadeli ETHUSDT fiyatları; gerçek borsa emri, API key veya para yatırma yok.
- İlk sanal bakiye 1.000 USDT. Nominal pozisyon en çok 1x, hedef stop riski %0,5.
- Kapanmış 1H mumda Donchian20 kırılımı ve kapanmış 4H trend filtresi. Sinyal 90 saniye içinde değerlendirilir; 30 saniyeden eski ETH fiyatıyla girilmez.
- Fiyat kayması varsayımı her yönde %0,03; taker komisyonu her yönde %0,06.
- Stop/hedef ilk 5dk mum dahil kapalı mumlardan izlenir. İkisi aynı mumda görünürse önce stop varsayılır. Azami bekleme 96 saattir.
- **Funding, değişken spread, işleme girme gecikmesi ve likidasyon bütünüyle modellenmedi. Sanal sonuçlar gerçek net kazanç garantisi değildir.**
- Bilgisayar kapalıysa izleme durur. Eksik mum yüzünden açık pozisyonun stop sonucu doğrulanamıyorsa deney PAUSED olur; sonuç uydurulmaz.
- Araştırma ufku 90 gün veya en az 50 kapalı sanal işlem. Bu eşik bile tek başına istatistiksel kârlılık kanıtı değildir.

## Kayıt ve Telegram

- pc_eth_forward_state.json: Açık sanal pozisyon, 1.000 USDT hesap, net getiri, maksimum gerçekleşmiş düşüş ve tamamlanan işlemler.
- pc_eth_forward_trades.jsonl: SANAL OPEN / CLOSE / PAUSED / SIGNAL_SKIPPED kayıtları.
- Her açılış ve kapanışta Telegram'da ETH 1H Donchian20 DENEYSEL SANAL uyarısı.
- Her iki JSON dosyası ve Telegram tokeni yereldir, gitignore ile GitHub paylaşımı engellenir.
- Durum ve işlem dosyalarını silme; uzun dönem performans ölçümlerini sıfırlar.

Çalışan eski BTC/ETH sinyal mantığı değişmedi; bu deney tamamen ayrı hesap üzerinden ilerler.
