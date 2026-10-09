# -*- coding: utf-8 -*-
"""Windows Bitget BTC/ETH live watcher. Public prices + CLOSED candles only; no orders."""
import datetime as dt
import getpass
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import websocket  # pip install websocket-client
except ImportError:
    sys.exit('websocket-client eksik. PC_BASLAT.bat dosyasini calistirin.')

import bitget_sinyal_takip as engine
import pc_zaman_dilimleri as multi

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / 'pc_telegram_ayar.json'
STATE_FILE = ROOT / 'pc_canli_durum.json'
WS_URL = 'wss://ws.bitget.com/v2/ws/public'
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
CANDLE_MS = multi.TF_MS['5m']
CLOSE_DELAY_MS = 5_000
MAX_SIGNAL_AGE_MS = 90_000
FRAMES = multi.FRAMES


def signal_key(symbol, timeframe):
    return f'{symbol}:{timeframe}'


def closed_bar(now_ms, timeframe='5m'):
    return multi.closed_bar(now_ms, timeframe, CLOSE_DELAY_MS)


def load_state(now_ms):
    state = engine.load_json(STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault('last_processed', {})
    state.setdefault('last_signal', {})
    baseline = closed_bar(now_ms)
    for symbol in SYMBOLS:
        # First start begins with NEXT finished candle: no historical alerts.
        state['last_processed'].setdefault(symbol, baseline)
    return state


def telegram_send(config, message):
    if not config.get('token') or not config.get('chat_id'):
        return False
    params = urllib.parse.urlencode({'chat_id': config['chat_id'], 'text': message}).encode()
    request = urllib.request.Request(
        'https://api.telegram.org/bot' + config['token'] + '/sendMessage',
        data=params, headers={'User-Agent': 'BitgetPCWatcher/1.0'})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.load(response)
    if not data.get('ok'):
        raise RuntimeError('Telegram mesaji reddetti')
    return True


def setup_telegram():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat = os.environ.get('TELEGRAM_CHAT_ID', '')
    if token and chat:
        return {'token': token, 'chat_id': chat}
    config = engine.load_json(CONFIG_FILE, {})
    if config.get('token') and config.get('chat_id'):
        return config
    print('\nTelegram kurulumu (anahtarlar yalnizca bu bilgisayarda saklanir).')
    print('BotFather botunu acin; tokeni ASLA GitHub veya sohbette paylasmayin.')
    token = getpass.getpass('Telegram bot tokeni (atlamak icin Enter): ').strip()
    if not token:
        print('Telegram kapali; sadece konsolda takip edilecek.')
        return {}
    chat = input('Telegram Chat ID: ').strip()
    if not chat:
        print('Chat ID yok; Telegram kapali.')
        return {}
    config = {'token': token, 'chat_id': chat}
    engine.save_json(CONFIG_FILE, config)
    return config


def format_signal(candidate, trends):
    label = 'LONG' if candidate['direction'] == 'LONG' else 'SHORT'
    now = dt.datetime.now(dt.timezone.utc).astimezone().strftime('%d.%m %H:%M')
    return (f'BITGET {candidate["symbol"]} {label} ADAY | {now}\n'
            f'5dk kapanis: {candidate["entry"]:,.2f} USDT\n'
            f'Stop: {candidate["stop"]:,.2f} | Hedef: {candidate["target"]:,.2f}\n'
            f'RSI: {candidate["rsi"]:.1f} | Hacim: {candidate["volume_ratio"]:.2f}x\n'
            f'15dk/1s/4s trend: {trends.get("15m")}/{trends.get("1H")}/{trends.get("4H")}\n'
            'UYARI: Sinyal adayi, kar garantisi yok. Gercek emir acilmaz.')


class Watcher:
    def __init__(self, config, clock=time.time):
        self.config = config
        self.clock = clock
        self.stop = threading.Event()
        self.price = {}
        self.last_tick = 0.0
        self.last_pong = 0.0
        self.ws = None
        self.state = load_state(int(clock() * 1000))
        self.retry_at = {sym: 0.0 for sym in SYMBOLS}

    def on_open(self, ws):
        self.last_pong = self.clock()
        args = [{'instType': 'USDT-FUTURES', 'channel': 'ticker', 'instId': s}
                for s in SYMBOLS]
        ws.send(json.dumps({'op': 'subscribe', 'args': args}))
        print('Bitget baglandi: BTC + ETH canli takip.')

    def on_message(self, ws, message):
        if message == 'pong':
            self.last_pong = self.clock()
            return
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        if data.get('event') == 'error' or (data.get('event') == 'subscribe' and data.get('code') not in (None, '0', '00000')):
            print('Bitget abonelik hatasi:', data.get('msg', 'bilinmiyor'))
            ws.close()
            return
        if data.get('arg', {}).get('channel') != 'ticker':
            return
        for tick in data.get('data', []):
            sym = tick.get('instId') or tick.get('symbol')
            if sym in SYMBOLS and tick.get('lastPr'):
                self.price[sym] = float(tick['lastPr'])
                self.last_tick = self.clock()

    def ws_loop(self):
        delay = 2
        while not self.stop.is_set():
            self.ws = websocket.WebSocketApp(WS_URL, on_open=self.on_open,
                on_message=self.on_message,
                on_error=lambda _ws, e: print('WebSocket:', str(e)[:160]),
                on_close=lambda _ws, *_: print('Baglanti kesildi; yeniden baglanilacak.'))
            try:
                self.ws.run_forever(ping_interval=0)
            except Exception as exc:
                print('Baglanti hatasi:', type(exc).__name__)
            if self.stop.is_set():
                break
            self.stop.wait(delay)
            delay = min(delay * 2, 60)

    def scan(self, symbol, bar):
        candidate, trends, reason = engine.analyze(symbol)
        if candidate and candidate['candle'] == bar:
            key = f'{candidate["direction"]}:{bar}'
            if self.state['last_signal'].get(symbol) != key:
                message = format_signal(candidate, trends)
                print('\n' + message + '\n')
                try:
                    telegram_send(self.config, message)
                except Exception as exc:
                    print('Telegram gonderilemedi:', type(exc).__name__)
                # Avoid duplicate spam even if Telegram is temporarily unreachable.
                self.state['last_signal'][symbol] = key
        else:
            print(f'{symbol}: sinyal yok ({reason}).')
        self.state['last_processed'][symbol] = bar
        engine.save_json(STATE_FILE, self.state)

    def process_candles(self):
        now = self.clock()
        now_ms = int(now * 1000)
        bar = closed_bar(now_ms)
        for sym in SYMBOLS:
            if self.state['last_processed'][sym] >= bar or self.retry_at[sym] > now:
                continue
            age_ms = now_ms - (bar + CANDLE_MS)
            if age_ms > MAX_SIGNAL_AGE_MS:
                print(sym, 'eski mum atlandi; gecmis sinyal yollanmayacak.')
                self.state['last_processed'][sym] = bar
                engine.save_json(STATE_FILE, self.state)
                continue
            try:
                self.scan(sym, bar)
            except Exception as exc:
                print(sym, 'analiz hatasi:', type(exc).__name__, str(exc)[:140])
                self.retry_at[sym] = now + 15

    def run(self):
        thread = threading.Thread(target=self.ws_loop, daemon=True)
        thread.start()
        print('Sinyaller yalnizca kapanmis 5dk mumlarda kontrol edilir.')
        print('Fiyatlar WebSocket ile canli guncellenir. Durdur: Ctrl+C\n')
        print_at = 0
        ping_at = 0
        while not self.stop.is_set():
            now = self.clock()
            if now >= ping_at:
                ws = self.ws
                if ws and ws.sock and ws.sock.connected:
                    try:
                        if self.last_pong and now - self.last_pong > 80:
                            ws.close()
                        elif self.last_tick and now - self.last_tick > 120:
                            print('Canli fiyat akisi durdu; tekrar baglaniyor.')
                            ws.close()
                        else:
                            ws.send('ping')
                    except Exception:
                        ws.close()
                ping_at = now + 25
            if now >= print_at:
                btc = f'{self.price["BTCUSDT"]:,.2f}' if 'BTCUSDT' in self.price else '--'
                eth = f'{self.price["ETHUSDT"]:,.2f}' if 'ETHUSDT' in self.price else '--'
                status = 'canli' if self.last_tick and now - self.last_tick < 30 else 'baglaniyor'
                print(f'{dt.datetime.now().strftime("%H:%M:%S")} | BTC {btc} | ETH {eth} | {status}')
                print_at = now + 30
            self.process_candles()
            self.stop.wait(1)


def main():
    # Only one copy can run on a single Windows PC; reduces duplicate messages.
    single = socket.socket()
    try:
        single.bind(('127.0.0.1', 49371))
    except OSError:
        sys.exit('Bot zaten acik olabilir. Iki kere baslatmayin.')
    config = setup_telegram()
    if config:
        try:
            telegram_send(config, 'Bitget PC canli takip basladi (BTC/ETH). Sadece sanal sinyaller, emir yok.')
            print('Telegram test bildirimi gonderildi.')
        except Exception as exc:
            print('Telegram test bildirimi BASARISIZ:', type(exc).__name__)
    bot = Watcher(config)
    try:
        bot.run()
    except KeyboardInterrupt:
        print('\nBot kapaniyor.')
    finally:
        bot.stop.set()
        if bot.ws:
            bot.ws.close()
        single.close()


if __name__ == '__main__':
    main()
