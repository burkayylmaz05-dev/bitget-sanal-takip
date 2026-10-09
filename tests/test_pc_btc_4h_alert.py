"""BTC 4H researched read-only alert safeguards. No internet or Telegram."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pc_btc_4h_alert as app


class BtcTrendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.boundary=12*app.FOUR
        self.alert=app.SignalAlert(
            now_ms=self.boundary-30000,
            state_file=Path(self.tmp.name)/'btc_state.json')
        self.now=self.boundary+15000
        self.expected_4h=self.boundary-app.FOUR
        self.expected_daily=self.boundary-app.DAY
        self.four=[(self.expected_4h,99,101,96,100,5)]
        self.daily=[(self.expected_daily,99,101,96,100,5)]
        self.signal={'PULLBACK_BIDIR':{self.boundary:{
            'd':1,'ref':100.0,'stop':97.0,'atr':2.0,
            'trail_mult':2.5,'signal_time':self.boundary}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_produces_one_alert_and_persists_dedup(self):
        with patch.object(app.candles,'history',return_value=(self.four,1)):
            with patch.object(app.study,'daily_candles',return_value=self.daily):
                with patch.object(app.study,'event_map',return_value=(self.signal,[])):
                    first=self.alert.check(self.now,quote=100.,quote_ms=self.now-1000)
                    self.assertIn('LONG ADAY',first)
                    self.assertIn('GERCEK EMIR YOK',first)
                    again=self.alert.check(self.now+1000,quote=100.,quote_ms=self.now)
                    self.assertIsNone(again)
        restored=app.SignalAlert(now_ms=self.now+2000,state_file=self.alert.state_file)
        self.assertEqual(restored.state['last_alert'],
                         self.alert.state['last_alert'])

    def test_no_replay_from_old_candle(self):
        late=self.boundary+app.MAX_AGE_MS+10000
        with patch.object(app.candles,'history') as fetch:
            self.assertIsNone(self.alert.check(late,quote=100.,quote_ms=late))
            fetch.assert_not_called()
        self.assertEqual(self.alert.state['last_bar'],self.expected_4h)

    def test_bad_or_stale_quote_never_processes_signal(self):
        with self.assertRaises(RuntimeError):
            self.alert.check(self.now,quote=100.,
                             quote_ms=self.now-app.MAX_TICK_AGE_MS-1)
        self.assertLess(self.alert.state['last_bar'],self.expected_4h)

    def test_waits_for_4h_and_daily_close_data(self):
        with patch.object(app.candles,'history',return_value=(
                [(self.expected_4h-app.FOUR,99,101,96,100,5)],1)):
            with self.assertRaisesRegex(RuntimeError,'4H closed'):
                self.alert.check(self.now,quote=100,quote_ms=self.now)
        self.assertLess(self.alert.state['last_bar'],self.expected_4h)
        with patch.object(app.candles,'history',return_value=(self.four,1)):
            with patch.object(app.study,'daily_candles',return_value=[
                    (self.expected_daily-app.DAY,99,101,96,100,5)]):
                with self.assertRaisesRegex(RuntimeError,'daily candle'):
                    self.alert.check(self.now,quote=100,quote_ms=self.now)

    def test_price_drift_drops_not_falsely_reports(self):
        with patch.object(app.candles,'history',return_value=(self.four,1)):
            with patch.object(app.study,'daily_candles',return_value=self.daily):
                with patch.object(app.study,'event_map',return_value=(self.signal,[])):
                    self.assertIsNone(self.alert.check(
                        self.now,quote=110,quote_ms=self.now))
        self.assertEqual(self.alert.state['last_bar'],self.expected_4h)


if __name__=='__main__':
    unittest.main()
