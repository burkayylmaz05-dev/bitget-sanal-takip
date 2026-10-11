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

    def test_exchange_clock_ahead_does_not_freeze_status(self):
        # Valid Bitget quote may be milliseconds/seconds ahead of local clock.
        self.book.on_quote('BTCUSDT', 83000., self.now + 8000, self.now)
        self.book.on_quote('ETHUSDT', 2500., self.now + 3000, self.now)
        status = self.book.snapshot()
        self.assertTrue(status['diagnostics']['BTCUSDT']['fresh'])
        self.assertTrue(status['diagnostics']['ETHUSDT']['fresh'])
        self.assertEqual(status['diagnostics']['BTCUSDT']['age_seconds'], 0.)
        # Excessive future skew and stale quotes must remain rejected.
        self.book.on_quote('BTCUSDT', 1., self.now + 20000, self.now)
        self.assertEqual(self.book.prices['BTCUSDT']['price'],83000.)
        self.book.on_quote('ETHUSDT', 1., self.now - 61000, self.now)
        self.assertEqual(self.book.prices['ETHUSDT']['price'],2500.)

    def test_status_snapshot_shows_missing_quotation(self):
        obj = self.book.snapshot()
        self.assertFalse(obj['diagnostics']['ETHUSDT']['fresh'])
        self.assertIsNone(obj['diagnostics']['ETHUSDT']['age_seconds'])
        self.assertEqual(obj['version'],'9.2')

    def test_manual_90_second_paper_test_opens_and_closes_independently(self):
        self.book.on_quote('BTCUSDT',83000.,self.now,self.now)
        self.book.on_quote('ETHUSDT',2500.,self.now,self.now)
        ok,msg=self.book.start_technical_test()
        self.assertTrue(ok,msg)
        self.assertEqual(len(self.book.technical['open']),2)
        self.assertEqual(self.book.accounts['BTCUSDT']['closed'],0)
        self.assertEqual(self.book.accounts['ETHUSDT']['closed'],0)
        again, _ =self.book.start_technical_test()
        self.assertFalse(again)
        later=self.now+app.TECH_DURATION_MS+1000
        self.book.on_quote('BTCUSDT',83000.,later,later)
        self.book.on_quote('ETHUSDT',2500.,later,later)
        self.assertEqual(len(self.book.technical['open']),0)
        self.assertEqual(len(self.book.technical['history']),2)
        self.assertTrue(all(x['net']<0 for x in self.book.technical['history']))
        for sym in app.SYMBOLS:
            self.assertEqual(self.book.accounts[sym]['equity'],1000.0)
        self.assertEqual(self.book.accounts[app.FAST_ID]['equity'],1000.0)

    def test_fast_15m_signal_creates_real_forward_paper_trade_separately(self):
        start = app.fresh_15m(self.now) - 299*app.FIFTEEN
        bars = []
        for i in range(300):
            close = 100 + i*.05 + (.5 if i==299 else 0)
            bars.append((start+i*app.FIFTEEN,close-.02,
                         close+.13,close-.13,close,100.))
        signal,reason=app.fast_signal_from_closed(bars)
        self.assertIsNotNone(signal,reason)
        self.assertEqual(signal['direction'],1)
        a=self.book.accounts[app.FAST_ID]
        a['last_bar']=bars[-1][0]-app.FIFTEEN
        fast_now=bars[-1][0]+app.FIFTEEN+11000
        self.book.on_fast_15m_close(bars,fast_now,bars[-1][4],
                                    fast_now-1000)
        p=a['position']
        self.assertIsNotNone(p)
        self.assertEqual(p['direction'],1)
        self.assertLessEqual(p['quantity']*p['entry'],1001.0)
        self.assertEqual(self.book.accounts['BTCUSDT']['equity'],1000.0)
        self.book.on_fast_15m_close(bars,fast_now,bars[-1][4],
                                    fast_now-1000)
        self.assertEqual(a['next_id'],2)
        self.book.on_quote('BTCUSDT',p['stop']-1,fast_now+15000,
                           fast_now+15000)
        self.assertEqual(a['closed'],1)
        self.assertIsNone(a['position'])
        self.assertLess(a['equity'],1000)
        self.assertEqual(self.book.accounts['BTCUSDT']['equity'],1000.)

    def test_fast_trade_restart_unverified_without_fake_gain(self):
        a=self.book.accounts[app.FAST_ID]
        a['position']={'id':'TEST-0001','direction':1,'entry':100,
                        'stop':90,'quantity':1.0,
                        'trail_atr':3.2,'deadline_ms':self.now+10000}
        self.book.save()
        second=app.Book(folder=self.path,now=lambda:self.now+5000)
        a2=second.accounts[app.FAST_ID]
        self.assertEqual(a2['unverified'],1)
        self.assertIsNone(a2['position'])
        self.assertEqual(a2['equity'],1000.)

    def test_versioned_browser_url_returns_fresh_v92_html(self):
        # Old tab on / can keep V9.1 static HTML. New launcher must open
        # /?v=9.2 with a cache buster and serve HTML, never a JSON document.
        import http.server
        import threading
        import urllib.request
        app.Handler.book = self.book
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            root=f"http://127.0.0.1:{server.server_address[1]}"
            with urllib.request.urlopen(root+"/?v=9.2&fresh=123",timeout=4) as r:
                html=r.read().decode("utf-8")
                self.assertIn("text/html",r.headers.get("Content-Type",""))
            self.assertIn("V9.2",html)
            self.assertIn("15 dakika",html)
            with urllib.request.urlopen(root+"/api/state?test=1",timeout=4) as r:
                data=json.load(r)
            self.assertEqual(data["version"],"9.2")
            self.assertIn("BTC15M",data["accounts"])
        finally:
            server.shutdown()
            server.server_close()

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
