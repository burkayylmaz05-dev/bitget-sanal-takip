# -*- coding: utf-8 -*-
"""Frozen BTC 4H pullback both directions on an OLDER UNSEEN historical period.

No optimization, no changed signals, no bourse orders, read-only Bitget.
The earlier sample ends where the 720-day recent sample starts.
"""
import datetime as dt
import json
import time
from pathlib import Path

import research_backtest as core
import research_trend_v4 as study

DAY=study.DAY
PERIOD=720
METHOD='PULLBACK_BIDIR'
OUT=Path(__file__).resolve().parent/'research_trend_older_report.json'


def dstr(ms):
    return dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).isoformat()


def main():
    current=int(time.time()*1000)//DAY*DAY
    earlier_end=current-720*DAY
    earlier_start=earlier_end-720*DAY
    warmup_end=earlier_start+260*DAY
    split=warmup_end+230*DAY
    report={'completed':False,'method':'BTCUSDT PULLBACK_BIDIR (FROZEN PARAMETERS)',
            'period':'prior to original 720-day study; not an entirely new market observation',
            'start_utc':dstr(earlier_start),'warmup_end_utc':dstr(warmup_end),
            'split_utc':dstr(split),'end_utc':dstr(earlier_end),
            'settings':{'taker_fee':.0006,'slippage':.0003,'stress_fee':.0012,
                        'stress_slippage':.0006,'funding_included':False,
                        'data_source':'Bitget v2 4H and 1Dutc historical futures'},
            'samples':{},'errors':[]}
    try:
        bars,_calls=core.history('BTCUSDT','4H',earlier_start,earlier_end)
        daily=study.daily_candles('BTCUSDT',earlier_start,earlier_end)
        signals,atr=study.event_map(bars,daily)
        for name,a,b in [('older_first_half',warmup_end,split),
                         ('older_second_half',split,earlier_end),
                         ('older_combined',warmup_end,earlier_end)]:
            one=study.simulate(bars,signals[METHOD],atr,a,b)
            stressed=study.simulate(bars,signals[METHOD],atr,a,b,fee=.0012,slip=.0006)
            bench=study.benchmark_long(bars,a,b)
            report['samples'][name]={'normal':one,'double_costs':stressed,'buy_hold_ref_pct':bench}
            print(name,'trades',one['trades'],'wins',one['wins'],
                  'return',one['return_pct'],'PF',one['profit_factor'],
                  'stress',stressed['return_pct'],'dd',one['max_drawdown_pct'],flush=True)
        report['bars']={'4h':len(bars),'daily':len(daily)}
        report['completed']=True
    except Exception as exc:
        report['errors'].append(f'{type(exc).__name__}: {str(exc)[:350]}')
        print('ERROR',report['errors'][-1],flush=True)
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('FINAL',report['completed'],report['errors'],flush=True)
    if not report['completed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
