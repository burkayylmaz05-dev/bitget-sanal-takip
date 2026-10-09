"""Offline tests for PC watcher: no exchange or Telegram requests."""
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

engine = types.ModuleType('bitget_sinyal_takip')
engine.load_json = lambda path, d: d if not path.exists() else json.loads(path.read_text())
engine.save_json = lambda path, obj: path.write_text(json.dumps(obj))
engine.analyze = lambda symbol: (None, {}, 'filtre')
ws = types.ModuleType('websocket')
ws.WebSocketApp = type('WebSocketApp', (), {})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Temporarily use fakes only while loading the PC watcher.
# Do not replace imported modules for the repository's other tests.
with patch.dict(sys.modules, {'bitget_sinyal_takip': engine, 'websocket': ws}):
    spec = importlib.util.spec_from_file_location(
        '_pc_canli_bot_test', Path(__file__).resolve().parent.parent / 'pc_canli_bot.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)


class LocalBotTests(unittest.TestCase):
    def test_closed_bar_5_second_grace(self):
        t = 13 * app.CANDLE_MS
        self.assertEqual(app.closed_bar(t+4999), 11 * app.CANDLE_MS)
        self.assertEqual(app.closed_bar(t+5000), 12 * app.CANDLE_MS)

    def test_first_start_never_alerts_old_candle(self):
        with tempfile.TemporaryDirectory() as p, patch.object(app, 'STATE_FILE', Path(p)/'s.json'):
            bot = app.Watcher({}, clock=lambda: 13*300)
            self.assertEqual(bot.state['last_processed']['BTCUSDT'], 11*300000)
            bot.process_candles()
            self.assertFalse((Path(p)/'s.json').exists())

    def test_new_candle_process_once(self):
        with tempfile.TemporaryDirectory() as p, patch.object(app, 'STATE_FILE', Path(p)/'s.json'):
            bot = app.Watcher({}, clock=lambda: 14*300+6)
            bot.state['last_processed'] = {s: 12*300000 for s in app.SYMBOLS}
            with patch.object(bot, 'scan', wraps=bot.scan) as scan:
                bot.process_candles()
                bot.process_candles()
                self.assertEqual(scan.call_count, 2)

    def test_sends_only_matching_closed_candle(self):
        with tempfile.TemporaryDirectory() as p, patch.object(app, 'STATE_FILE', Path(p)/'s.json'):
            bot = app.Watcher({}, clock=lambda: 300*15)
            bar = 13*300000
            candidate = dict(symbol='BTCUSDT', direction='SHORT', candle=bar, entry=100,
                             stop=102, target=95, rsi=42, volume_ratio=1.9)
            with patch.object(engine, 'analyze', return_value=(
                candidate, {'15m': 'SHORT', '1H': 'SHORT', '4H': 'SHORT'}, 'ADAY')):
                with patch.object(app, 'telegram_send') as send:
                    bot.scan('BTCUSDT', bar)
                    bot.scan('BTCUSDT', bar)
                    self.assertEqual(send.call_count, 1)

    def test_ws_ticker_parse(self):
        bot = app.Watcher({}, clock=lambda: 123.0)
        bot.on_message(None, json.dumps({'arg': {'channel': 'ticker'},
                        'data': [{'instId': 'BTCUSDT', 'lastPr': '82500.5'}]}))
        self.assertEqual(bot.price['BTCUSDT'], 82500.5)


if __name__ == '__main__':
    unittest.main()
