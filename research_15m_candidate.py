# -*- coding: utf-8 -*-
"""2026 15m BTC ETH forward-candidate comparison; no orders / no keys.

Reuses unchanged signal code from research_1h_frozen_compare applied to
actual Bitget 15m perpetual candles. Stop-first same-bar conservative,
entry next 15m open, full fee and slippage. Train first half of most recent
80 days, validate later 40 days. Lookback additional 6 days for EMA200.
NO funding and real order book; positive != validated forward profitability.
"""
import datetime as dt
import json
import time
import research_backtest as api
import research_1h_frozen_compare as strategies

MIN15=900000
DAY=86400000
METHODS=strategies.METHODS
SYMS=('BTCUSDT','ETHUSDT')


def main():
    end=(int(time.time()*1000)//MIN15)*MIN15
    test_start=end-40*DAY
    dev_start=test_start-40*DAY
    warmup_start=dev_start-8*DAY
    result={}
    for symbol in SYMS:
        rows,calls=api.history(symbol,'15m',warmup_start,end)
        feat=strategies.features(rows)
        print('CANDLES',symbol,len(rows),'pages',calls,flush=True)
        for method in METHODS:
            dev=strategies.run(rows,feat,method,dev_start,test_start)
            test=strategies.run(rows,feat,method,test_start,end)
            stress=strategies.run(rows,feat,method,test_start,end,fee=.0012,slip=.0006)
            result[symbol+':'+method]={
                'train':dev,'unseen_recent_40d':test,
                'test_costs_x2':stress}
            print('RESULT',symbol,method,
                  'train',dev['net_including_open_pct'],
                  'test',test['net_including_open_pct'],
                  'stress',stress['net_including_open_pct'],
                  'test_closes',test['closed'],flush=True)
    ranked=sorted(
        [(k,v) for k,v in result.items() if v['train']['closed']>=15],
        key=lambda x:(x[1]['train']['net_including_open_pct'],
                      x[1]['train']['max_marked_drawdown_pct']),reverse=True)
    selection=ranked[0][0] if ranked else None
    print('SELECTION_TRAIN_ONLY',selection,flush=True)
    print('RESULT_FULL_JSON',json.dumps({
        'end_utc':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
        'selection':selection,'results':result,'selection_rule':'development_only_min15',
        'trade_orders':False,'fee_each_side':.0006,
        'slippage_each_side':.0003,'funding_included':False},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
