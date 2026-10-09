"""Public API smoke test for BTC 4H alert. NEVER sends Telegram/Bitget orders.

Replays the latest actually CLOSED 4H candle using its close as mock live quote.
This validates Bitget history paging and UTC daily joins, NOT trade profit.
"""
import tempfile
import time
from pathlib import Path

import pc_btc_4h_alert as btc
import research_backtest as data


def main():
    now=int(time.time()*1000)
    bar=btc.last_closed_4h(now)
    closed_at=bar+btc.FOUR
    replay_time=closed_at+20000
    four,_=data.history('BTCUSDT','4H',closed_at-3*btc.DAY,closed_at)
    if four[-1][0]!=bar:
        raise RuntimeError('Bitget latest closed 4h candle stale')
    close=float(four[-1][4])
    with tempfile.TemporaryDirectory() as d:
        probe=btc.SignalAlert(now_ms=closed_at-30000,
                              state_file=Path(d)/'test_state.json')
        assert probe.state['last_bar']<bar
        alert=probe.check(replay_time,quote=close,quote_ms=replay_time-1000)
        assert probe.state['last_bar']==bar, '4H candle not analyzed'
        print('BTC 4H REAL-API SMOKE PASSED:', 'candidate found' if alert else 'no candidate')
        print('UTC closed bar',bar,'4h close',close)
        if alert:
            print(alert.splitlines()[0])
        # repeated bar must NOT retrigger.
        assert probe.check(replay_time+500,quote=close,quote_ms=replay_time) is None


if __name__=='__main__':
    main()
