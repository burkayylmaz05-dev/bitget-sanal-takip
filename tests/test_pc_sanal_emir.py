"""Deterministic offline live-paper tests. No keys, API, Telegram or exchange orders."""
import json
import tempfile
import unittest
from pathlib import Path

import pc_sanal_emir as paper

FIVE=paper.FIVE


def candles(last_open, crossing='UP'):
    n=70
    if crossing=='UP':
        closes=[100.0]*(n-2)+[99.0,101.0]
    else:
        closes=[100.0]*(n-2)+[101.0,99.0]
    return [
        (last_open-(n-1-i)*FIVE,100.0,max(100.5,c+.5),
         min(99.5,c-.5),c,50.0)
        for i,c in enumerate(closes)
    ]


class PaperOrders(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)
        self.start=3*FIVE-180_000
        self.book=paper.PaperBook(
            self.start,self.path/'state.json',
            self.path/'events.jsonl',self.path/'results.txt')

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_quote_creates_and_closes_two_explicit_tests_but_not_strategy_pnl(self):
        b=self.book
        opened1=b.on_quote('BTCUSDT',85000.0,self.start+1000,now_ms=self.start+1000)
        opened2=b.on_quote('ETHUSDT',2600.0,self.start+1000,now_ms=self.start+1000)
        self.assertEqual(len(opened1),1)
        self.assertEqual(len(opened2),1)
        self.assertIn('TEKNIK SISTEM TESTI',opened1[0])
        self.assertIn('SANAL EMIR ACILDI',opened2[0])
        self.assertEqual(b.on_quote('BTCUSDT',85000,self.start+1000,now_ms=self.start+1000),[])
        done=b.on_quote('BTCUSDT',85010,self.start+92_000,now_ms=self.start+92_000)
        done2=b.on_quote('ETHUSDT',2590,self.start+92_000,now_ms=self.start+92_000)
        self.assertEqual(len(done),len(done2))
        self.assertIn('NET:',done[0])
        self.assertIn('STRATEJI KARI DEGIL',done[0])
        for sym in paper.SYMBOLS:
            a=b.state['accounts'][sym]
            self.assertTrue(a['test_done'])
            self.assertIsNotNone(a['test_pnl'])
            self.assertEqual(a['balance'],1000.0)
            self.assertEqual(a['closed'],0)
        events=[json.loads(x) for x in (self.path/'events.jsonl').read_text().splitlines()]
        self.assertEqual([e['event'] for e in events],['OPEN','OPEN','CLOSE','CLOSE'])
        self.assertTrue((self.path/'results.txt').exists())

    def test_ema_cross_creates_strategy_trade_then_stop_net_loss(self):
        b=self.book
        b.state['accounts']['BTCUSDT']['test_done']=True
        now=3*FIVE+10_000
        candle_open=2*FIVE
        signals=b.on_closed_5m('BTCUSDT',candles(candle_open),
                                101.0,now-100,now)
        self.assertEqual(len(signals),1)
        self.assertIn('5DK EMA21 STRATEJI DENEMESI',signals[0])
        account=b.state['accounts']['BTCUSDT']
        pos=account['open']
        self.assertEqual(pos['kind'],paper.STRATEGY_NAME)
        self.assertGreater(pos['stop'],0)
        self.assertLess(pos['stop'],101)
        self.assertGreater(pos['target'],101)
        self.assertEqual(b.on_closed_5m('BTCUSDT',candles(candle_open),
                                         101.0,now,now),[])
        loss=b.on_quote('BTCUSDT',pos['stop']-2,
                        now+1000,now_ms=now+1000)
        self.assertEqual(len(loss),1)
        self.assertIn('SANAL EMIR KAPANDI',loss[0])
        self.assertEqual(account['closed'],1)
        self.assertEqual(account['losses'],1)
        self.assertLess(account['balance'],1000.0)
        self.assertEqual(account['wins'],0)
        self.assertIn('1 kapanan',b.status())

    def test_real_market_short_when_cross_down_and_take_profit(self):
        b=self.book
        b.state['accounts']['ETHUSDT']['test_done']=True
        now=3*FIVE+10_000
        s=b.on_closed_5m('ETHUSDT',candles(2*FIVE,'DOWN'),
                         99,now-500,now)
        self.assertEqual(len(s),1)
        acc=b.state['accounts']['ETHUSDT']
        p=acc['open']
        self.assertEqual(p['direction'],-1)
        close=b.on_quote('ETHUSDT',p['target']-1,now+1000,now+1000)
        self.assertEqual(len(close),1)
        self.assertEqual(acc['closed'],1)
        self.assertEqual(acc['wins'],1)
        self.assertGreater(acc['balance'],1000)

    def test_no_duplicate_stale_quote_or_lookback_replays(self):
        b=self.book
        b.state['accounts']['BTCUSDT']['test_done']=True
        now=3*FIVE+10_000
        a=b.state['accounts']['BTCUSDT']
        self.assertEqual(b.on_quote('BTCUSDT',100,now-20_000,now),[])
        self.assertIsNone(a['open'])
        b.on_closed_5m('BTCUSDT',candles(2*FIVE),101,now-20000,now)
        self.assertIsNone(a['open'])
        self.assertEqual(a['last_5m'],2*FIVE)
        self.assertEqual(b.on_closed_5m('BTCUSDT',candles(2*FIVE),
                                         101,now,now),[])

    def test_unverified_restart_discloses_missing_exit_and_does_not_credit_pnl(self):
        b=self.book
        b.on_quote('BTCUSDT',85000,self.start+1000,self.start+1000)
        again=paper.PaperBook(self.start+110_000,b.state_file,b.events_file,b.report_file)
        a=again.state['accounts']['BTCUSDT']
        self.assertIsNone(a['open'])
        self.assertEqual(a['unverified_aborts'],1)
        self.assertTrue(a['test_done'])
        self.assertIsNone(a['test_pnl'])
        self.assertEqual(a['closed'],0)
        self.assertEqual(a['balance'],1000.0)
        records=[json.loads(x) for x in again.events_file.read_text().splitlines()]
        self.assertEqual(records[-1]['event'],'UNVERIFIED_RESTART')
        self.assertIsNone(records[-1]['pnl_usdt'])

    def test_missing_ticks_stop_tracking_without_imaginary_profit(self):
        b=self.book
        b.on_quote('BTCUSDT',85000,self.start+1000,self.start+1000)
        m=b.on_quote('BTCUSDT',86000,self.start+200_000,self.start+200_000)
        self.assertIn('VERI BOSLUGU',m[0])
        a=b.state['accounts']['BTCUSDT']
        self.assertEqual(a['closed'],0)
        self.assertIsNone(a['test_pnl'])
        self.assertEqual(a['unverified_aborts'],1)
        self.assertIsNone(a['open'])


if __name__=='__main__':
    unittest.main()
