"""Offline tests of 5m/15m/1H/4H Windows watcher; no internet requests."""
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bitget_sinyal_takip as engine
import pc_zaman_dilimleri as multi

ws = types.ModuleType('websocket')
ws.WebSocketApp = type('WebSocketApp', (), {})
with patch.dict(sys.modules, {'websocket': ws}):
    spec = importlib.util.spec_from_file_location(
        '_pc_canli_bot_test', Path(__file__).resolve().parent.parent / 'pc_canli_bot.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)


class LocalBotTests(unittest.TestCase):
    def test_closed_bar_four_intervals_and_five_second_grace(self):
        for tf, step in multi.TF_MS.items():
            t = 13 * step
            self.assertEqual(app.closed_bar(t + 4999, tf), 11 * step)
            self.assertEqual(app.closed_bar(t + 5000, tf), 12 * step)

    def test_first_start_never_alerts_old_candles(self):
        with tempfile.TemporaryDirectory() as p, patch.object(app, 'STATE_FILE', Path(p) / 's.json'):
            t = 13 * 900
            bot = app.Watcher({}, clock=lambda: t)
            for sym in app.SYMBOLS:
                for tf in app.FRAMES:
                    self.assertEqual(bot.state['last_processed'][app.signal_key(sym, tf)],
                                     app.closed_bar(t * 1000, tf))
            with patch.object(multi, 'fetch_market') as fetch:
                bot.process_candles()
                fetch.assert_not_called()
            self.assertFalse((Path(p) / 's.json').exists())

    def test_three_intervals_at_hour_close_once_each(self):
        with tempfile.TemporaryDirectory() as p, patch.object(app, 'STATE_FILE', Path(p) / 's.json'):
            now = [3600.0]
            bot = app.Watcher({}, clock=lambda: now[0])
            now[0] += 6
            market = {tf: [(app.closed_bar(int(now[0] * 1000), tf), 1, 2, 1, 1.5, 1)]
                      for tf in app.FRAMES}
            with patch.object(multi, 'fetch_market', return_value=market) as fetch:
                with patch.object(multi, 'analyze', return_value=(None, {}, 'filtre')) as analyze:
                    bot.process_candles()
                    bot.process_candles()
                    self.assertEqual(fetch.call_count, 2)  # one download per symbol
                    self.assertEqual(analyze.call_count, 6)  # 5m,15m,1H per symbol
            for sym in app.SYMBOLS:
                for tf in ('5m', '15m', '1H'):
                    self.assertEqual(bot.state['last_processed'][app.signal_key(sym, tf)],
                                     app.closed_bar(int(now[0] * 1000), tf))
                self.assertEqual(bot.state['last_processed'][app.signal_key(sym, '4H')],
                                 app.closed_bar(3600_000, '4H'))

    def test_four_hour_signal_scanned_at_four_hour_close(self):
        with tempfile.TemporaryDirectory() as p, patch.object(app, 'STATE_FILE', Path(p) / 's.json'):
            now = [4 * 3600.0]
            bot = app.Watcher({}, clock=lambda: now[0])
            now[0] += 6
            market = {tf: [(app.closed_bar(int(now[0] * 1000), tf), 1, 2, 1, 1.5, 1)]
                      for tf in app.FRAMES}
            with patch.object(multi, 'fetch_market', return_value=market):
                with patch.object(multi, 'analyze', return_value=(None, {}, 'filtre')) as analyze:
                    bot.process_candles()
                    self.assertEqual(analyze.call_count, 8)

    def test_duplicate_suppression_is_per_symbol_and_timeframe(self):
        with tempfile.TemporaryDirectory() as p, patch.object(app, 'STATE_FILE', Path(p) / 's.json'):
            bot = app.Watcher({}, clock=lambda: 3600)
            bar = 2 * 900_000
            candidate = dict(symbol='BTCUSDT', timeframe='15m', direction='SHORT',
                             candle=bar, entry=100, stop=102, target=95,
                             rsi=42, volume_ratio=1.9)
            with patch.object(multi, 'analyze', return_value=(
                    candidate, {'5m':'SHORT','15m':'SHORT','1H':'SHORT','4H':'SHORT'}, 'ADAY')):
                with patch.object(app, 'telegram_send') as send:
                    bot.scan('BTCUSDT', '15m', bar, {})
                    bot.scan('BTCUSDT', '15m', bar, {})
                    self.assertEqual(send.call_count, 1)
                    self.assertTrue((Path(p) / 's.json').exists())

    def test_stale_signal_is_not_sent(self):
        with tempfile.TemporaryDirectory() as p, patch.object(app, 'STATE_FILE', Path(p) / 's.json'):
            t = [900.0]
            bot = app.Watcher({}, clock=lambda: t[0])
            t[0] += 200  # too late after 15m close
            with patch.object(multi, 'fetch_market') as fetch:
                bot.process_candles()
                fetch.assert_not_called()

    def test_ws_ticker_arg_fallback(self):
        bot = app.Watcher({}, clock=lambda: 123.0)
        bot.on_message(None, json.dumps({'arg': {'channel': 'ticker', 'instId': 'BTCUSDT'},
                         'data': [{'lastPr': '82500.5'}]}))
        self.assertEqual(bot.price['BTCUSDT'], 82500.5)

    def test_trend_gate_is_independent(self):
        data = {tf: [(0, 1, 2, 0.5, 1, 1)] for tf in multi.FRAMES}
        with patch.object(engine, 'classify', side_effect=['LONG', 'LONG', 'LONG', 'SHORT']):
            candidate, trends, reason = multi.analyze('BTCUSDT', '15m', data)
            self.assertIsNone(candidate)
            self.assertIn('uyumsuz', reason)
            self.assertEqual(trends['4H'], 'SHORT')


if __name__ == '__main__':
    unittest.main()
