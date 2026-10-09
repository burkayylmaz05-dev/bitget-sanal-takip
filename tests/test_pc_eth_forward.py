"""Offline tests for isolated ETH 1H forward-paper tracking. No API keys/net."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pc_eth_forward as forward

HOUR = forward.HOUR
FIVE = forward.FIVE


def rows(hour, open_price=100.0):
    return {
        '1H': [(hour, 100, 110, 95, 101, 1)],
        '4H': [(hour - 4 * HOUR, 100, 110, 95, 101, 1)],
        '5m': [(hour-FIVE, 100, 105, 95, 101, 1)]
    }


def candidate(decision):
    return {
        'symbol':'ETHUSDT', 'time':decision, 'reference':100.0,
        'direction':1, 'stop':98.0, 'target':104.0, 'timeout':96*HOUR,
        'atr':1.0, 'frame':'1H', 'method':'H1_CHANNEL20'
    }


class ForwardPaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        self.before = 13*HOUR - 60_000
        self.experiment = forward.PaperExperiment(
            self.before, folder/'state.json', folder/'trades.jsonl')

    def tearDown(self):
        self.temp.cleanup()

    def open_trade(self):
        now = 13*HOUR + 10_000
        with patch.object(forward, 'evaluate_signal',
                          return_value=(candidate(13*HOUR), 'candidate')) as signal:
            alerts = self.experiment.on_market(
                rows(12*HOUR), now, eth_price=100.0, eth_quote_ms=now-1000)
        self.assertEqual(len(alerts), 1)
        self.assertIn('Sanal'.upper(), alerts[0].upper())
        signal.assert_called_once()
        return now

    def test_state_persisted_and_duplicate_not_opened(self):
        now = self.open_trade()
        e = self.experiment
        with patch.object(forward, 'evaluate_signal') as sig:
            second = e.on_market(rows(12*HOUR), now+1000,
                                 eth_price=100.,eth_quote_ms=now)
        self.assertEqual(second, [])
        sig.assert_not_called()
        self.assertIsNotNone(e.state['open'])
        self.assertGreater(e.state['open']['qty'], 0)
        self.assertLessEqual(e.state['open']['entry']*e.state['open']['qty'], 1000.01)
        reloaded = forward.PaperExperiment(
            now+30_000,e.state_file,e.history_file)
        self.assertEqual(reloaded.state['open']['entry'], e.state['open']['entry'])
        self.assertEqual(len(e.history_file.read_text(encoding='utf-8').splitlines()), 1)

    def test_initial_five_minute_stop_overrides_take(self):
        self.open_trade()
        t = 13*HOUR+FIVE+10_000
        data=rows(12*HOUR)
        data['5m']=[
            (13*HOUR, 100, 110, 96, 100, 1)
        ]
        alerts=self.experiment.on_market(data,t,eth_price=102,eth_quote_ms=t-1000)
        self.assertEqual(len(alerts),1)
        self.assertIn('STOP',alerts[0])
        s=self.experiment.state
        self.assertIsNone(s['open'])
        self.assertEqual(s['closed'],1)
        self.assertEqual(s['losses'],1)
        self.assertLess(s['equity'],1000)
        self.assertEqual(len(self.experiment.history_file.read_text(encoding='utf-8').splitlines()),2)

    def test_gap_suspends_not_pays_winner(self):
        self.open_trade()
        jump=13*HOUR+FIVE*7+10_000
        data=rows(12*HOUR)
        data['5m']=[(13*HOUR+FIVE*5,100,110,95,104,1)]
        alerts=self.experiment.on_market(data,jump,eth_price=100,eth_quote_ms=jump-1000)
        self.assertEqual(len(alerts),1)
        self.assertTrue(self.experiment.state['paused'])
        self.assertEqual(self.experiment.state['closed'],0)
        self.assertIsNotNone(self.experiment.state['open'])
        self.assertEqual(self.experiment.state['equity'],1000)
        self.assertEqual(self.experiment.on_market(data,jump+10_000),[])

    def test_no_fresh_quote_skips_signal_without_entering(self):
        now=13*HOUR+10_000
        with patch.object(forward,'evaluate_signal',
                          return_value=(candidate(13*HOUR),'candidate')):
            alerts=self.experiment.on_market(rows(12*HOUR),now,
                                             eth_price=100,eth_quote_ms=now-50_000)
        self.assertEqual(alerts,[])
        self.assertIsNone(self.experiment.state['open'])
        self.assertEqual(self.experiment.state['last_hour'],12*HOUR)

    def test_old_signal_ignored_after_offline_time(self):
        now=13*HOUR+180_000
        with patch.object(forward,'evaluate_signal') as signal:
            alerts=self.experiment.on_market(rows(12*HOUR),now,
                                             eth_price=100,eth_quote_ms=now)
        self.assertFalse(alerts)
        signal.assert_not_called()
        self.assertIsNone(self.experiment.state['open'])

    def test_asof_higher_candle_only(self):
        # At 13:00 last closed 4H candle opened at 08:00 and closed at 12:00.
        hour=12*HOUR
        one=[(hour-(240-i)*HOUR,100.,101.,99.,100.,1.) for i in range(241)]
        four=[(hour-(241-i)*FOUR,100.,101.,99.,100.,1.) for i in range(242)]
        # Later, 12:00 4h candle is still open at 13:00 and must not be used.
        four.append((12*HOUR,100.,101.,99.,100.,1.))
        with patch.object(forward.rules,'make_signal',return_value=None) as call:
            forward.evaluate_signal(one,four,hour)
        self.assertTrue(call.called)
        j=call.call_args.args[6]
        self.assertLessEqual(four[j][0]+FOUR, hour+HOUR)


if __name__ == '__main__':
    unittest.main()
