"""Offline, deterministic and no-order tests for standalone V9 paper dashboard."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pc_sanal_v9 as app

FOUR = app.FOUR
DAY = app.DAY


def synthetic_rows(close_final=102.6):
    first = 620 * FOUR
    rows = []
    for i in range(120):
        c = close_final if i == 119 else 100.0
        high = 103.0 if i == 119 else 101.4
        low = 99.0 if i == 119 else 98.6
        rows.append((first + i * FOUR, 100.0, high, low, c, 100.0))
    return rows


def daily_up():
    return [(i*DAY, 100.0 + i*.10, 101.0+i*.10, 99+i*.10,
             100+i*.10, 1000.) for i in range(620)]


def daily_down():
    return [(i*DAY, 300.0 - i*.10, 301.0-i*.10, 299.0-i*.10,
             300-i*.10, 1000.) for i in range(620)]


class V9Tests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)
        self.rows = synthetic_rows()
        self.last = self.rows[-1][0]
        self.now = self.last + FOUR + 11_000
        self.book = app.Book(folder=self.path, now=lambda: self.now)

    def tearDown(self):
        self.folder.cleanup()

    def test_signal_uses_closed_4h_daily_trend_and_actual_preceding_channel(self):
        event, reason = app.signal_from_closed('BTCUSDT', self.rows, daily_up())
        self.assertEqual(reason, 'ADAY')
        self.assertEqual(event['direction'], 1)
        self.assertLess(event['stop'], event['reference'])
        self.assertEqual(event['signal_at'], self.last + FOUR)
        eth, why = app.signal_from_closed('ETHUSDT', self.rows, daily_up())
        self.assertIsNotNone(eth)
        self.assertEqual(eth['direction'], 1)

    def test_wrong_daily_regime_no_false_long_signal(self):
        event, reason = app.signal_from_closed('BTCUSDT', self.rows, daily_down())
        self.assertIsNone(event)
        self.assertIn('uyusmuyor', reason)

    def test_open_close_and_csv_exactly_one_each_costs_and_equity(self):
        a = self.book.accounts['BTCUSDT']
        a['last_bar'] = self.last-FOUR
        self.book.on_4h_close('BTCUSDT', self.rows, daily_up(),
                              self.now, 102.7, self.now-1000)
        p = a['position']
        self.assertIsNotNone(p)
        self.assertEqual(p['direction'], 1)
        self.assertLessEqual(p['quantity']*p['entry'], 1000.01)
        self.assertGreater(p['stop'], 0)
        self.book.on_4h_close('BTCUSDT', self.rows, daily_up(),
                              self.now, 102.7, self.now-1000)
        self.assertEqual(a['next_id'], 2)
        # Liquidation never occurs; fake paper stop closes at worse price.
        self.book.on_quote('BTCUSDT', p['stop']-2, self.now+1000,self.now+1000)
        self.assertEqual(a['closed'], 1)
        self.assertEqual(a['losses'], 1)
        self.assertIsNone(a['position'])
        self.assertLess(a['equity'],1000)
        csv_content=(self.path/app.LOG_PATH.name).read_text(encoding='utf-8-sig')
        self.assertEqual(csv_content.count('SANAL_ACILIS'),1)
        self.assertEqual(csv_content.count('SANAL_KAPANIS'),1)

    def test_stale_close_cannot_open_retroactive_position(self):
        a = self.book.accounts['BTCUSDT']
        a['last_bar'] = self.last-FOUR
        late=self.now+app.MAX_SIGNAL_DELAY_MS+1000
        self.book.on_4h_close('BTCUSDT',self.rows,daily_up(),late,
                              102.7,late-1000)
        self.assertIsNone(a['position'])
        self.assertEqual(a['last_bar'],self.last)

    def test_unverified_restart_no_invented_pnl_or_repeat_entry(self):
        a=self.book.accounts['BTCUSDT']
        a['last_bar']=self.last-FOUR
        self.book.on_4h_close('BTCUSDT',self.rows,daily_up(),
                              self.now,102.7,self.now-1000)
        self.assertIsNotNone(a['position'])
        restarted=app.Book(folder=self.path, now=lambda:self.now+300000)
        b=restarted.accounts['BTCUSDT']
        self.assertIsNone(b['position'])
        self.assertEqual(b['unverified'],1)
        self.assertEqual(b['closed'],0)
        self.assertEqual(b['equity'],1000)
        csv=(self.path/app.LOG_PATH.name).read_text(encoding='utf-8-sig')
        self.assertIn('DOGRULANAMADI',csv)

    def test_no_exchange_order_api_and_no_credentials_required(self):
        source=(Path(__file__).resolve().parent.parent/'pc_sanal_v9.py').read_text()
        self.assertNotIn('mix/order/place-order',source)
        self.assertNotIn('mix/order/placeOrder',source)
        self.assertNotIn('import ccxt',source)
        self.assertEqual(self.book.telegram,{})
        snapshot=self.book.snapshot()
        self.assertEqual(snapshot['accounts']['BTCUSDT']['closed'],0)
        self.assertIn('historical_research',snapshot)


if __name__=='__main__':
    unittest.main()
