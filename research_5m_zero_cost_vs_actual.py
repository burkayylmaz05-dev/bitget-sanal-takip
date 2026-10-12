# -*- coding: utf-8 -*-
"""Audit if 2026 BTC/ETH 5m V10.1 original has ANY gross edge before costs.

Frozen V101_D55 and H4 trend filter. Uses genuine Bitget last 40d
5m historical public futures bars, same signal and fill engine from
research_v101_5m_robust.py, no orders or user API keys.
Compare NONE vs standard 6bp fee + 3bp slip / each side vs 2x.
"""
import datetime as dt
import json
import time
import research_backtest as api
import research_v101_5m_robust as old

DAY=86400000
FIVE=300000
def main():
    end=int(time.time()*1000)//FIVE*FIVE
    start=end-40*DAY
    outputs={}
    for sym in ('BTCUSDT','ETHUSDT'):
        bars,npages=api.history(sym,'5m',start-7*DAY,end)
        four,_=api.history(sym,'4H',start-225*DAY,end)
        ev,atr=old.signal_map(bars,four)
        for method in ('V101_D55','D55_4H_TREND','D55_4H_TREND_HIGH_ATR'):
            zero=old.replay(bars,ev[method],atr,start,end,fee=0,slip=0)
            standard=old.replay(bars,ev[method],atr,start,end)
            stressed=old.replay(bars,ev[method],atr,start,end,fee=.0012,slip=.0006)
            outputs[sym+':'+method]={
                'zero_cost':zero,'normal':standard,'double_cost':stressed}
            print('COST_DECAY',sym,method,'zero',zero['net_pct'],
                  'standard',standard['net_pct'],
                  'double',stressed['net_pct'],
                  'closed',standard['closed'],flush=True)
    print('FIVE_MIN_COST_AUDIT_JSON',json.dumps({
        'period_utc':[dt.datetime.fromtimestamp(start/1000,dt.timezone.utc).isoformat(),
                      dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat()],
        'read_only':True,'results':outputs,'initial_notional_limit':1,
        'zero_cost_is_idealized_not_possible_in_real_exchange':True},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
