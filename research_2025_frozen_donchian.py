# -*- coding: utf-8 -*-
"""Truly frozen older 2025 cross-check of 2026-screened BTC 4h Donchian20/55.

Uses identical 2026 tested rules, copied via import, on older FULL 2025;
2024 only for warmup. No new optimization. Fee/slip includes x2 stress.
Read-only public Bitget. No keys, no trading orders.
"""
import datetime as dt
import json

import research_backtest as data
import research_trend_v4 as core
import research_2026_4h_external_rules as algo


def timestamp(value):
    return int(dt.datetime.fromisoformat(value).replace(tzinfo=dt.timezone.utc).timestamp()*1000)


def main():
    warmup=timestamp('2024-01-01')
    first=timestamp('2025-01-01')
    split=timestamp('2025-07-01')
    end=timestamp('2026-01-01')
    outputs={}
    for sym in ('BTCUSDT','ETHUSDT'):
        four,pages=data.history(sym,'4H',warmup,end)
        daily=core.daily_candles(sym,warmup,end)
        maps,atr=algo.build_events(four,daily)
        for method in ('DONCHIAN20_FILTER','DONCHIAN55_FILTER'):
            e=maps[method]
            first_result=algo.simulate(four,e,atr,first,split)
            second_result=algo.simulate(four,e,atr,split,end)
            double=algo.simulate(four,e,atr,split,end,fee=.0012,slip=.0006)
            outputs[f'{sym}:{method}']={'2025_H1':first_result,
                '2025_H2':second_result,'2025_H2_COST_2X':double}
            print('RESULT',sym,method,first_result['net_pct'],
                  second_result['net_pct'],double['net_pct'],
                  first_result['trades'],second_result['trades'],flush=True)
    print('FROZEN_2025_JSON',json.dumps(outputs,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
