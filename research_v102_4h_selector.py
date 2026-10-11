# -*- coding: utf-8 -*-
"""Predefined multiyear BTC/ETH 4H trend methodology verification.

2025 for development, 2026 for later historical review; two halves each.
Every 4H trade fills at next bar open, including initial-bar stop; pessimistic
same bar stop. Taker fee .06% each side, adverse slip .03% each side,
1x notional, .5% stop risk. Costs twice normal are stress tested.
BTC/ETH perp funding except separate 89d audit is NOT modeled.
Accounts are NEVER accessed or traded. Candidate selection uses 2025 ONLY.
"""
import datetime as dt
import json
import research_backtest as api
import research_2026_4h_external_rules as signals
import research_trend_v4 as old

DAY=86400000

def ms(date):
    return int(dt.datetime.fromisoformat(date).replace(
        tzinfo=dt.timezone.utc).timestamp()*1000)

def report_window(bars,f,event,lo,hi):
    x=signals.simulate(bars,event,f,ms(lo),ms(hi))
    stress=signals.simulate(bars,event,f,ms(lo),ms(hi),fee=.0012,slip=.0006)
    return {'pct':x['net_pct'],'trades':x['trades'],'wins':x['wins'],
            'dd_pct':x['max_dd_pct'],'profit_factor':x['profit_factor'],
            'stress_pct':stress['net_pct']}

def main():
    start=ms('2024-01-01')
    end=ms('2026-10-11')
    splits=[
        ('2025_H1','2025-01-01','2025-07-01'),
        ('2025_H2','2025-07-01','2026-01-01'),
        ('2026_H1','2026-01-01','2026-07-01'),
        ('2026_H2','2026-07-01','2026-10-11')]
    outputs={}
    for sym in ('BTCUSDT','ETHUSDT'):
        bars,_=api.history(sym,'4H',start,end)
        daily=old.daily_candles(sym,start,end)
        eventmaps, atrs=signals.build_events(bars,daily)
        # Frozen alternatives include both short-enabled and long-only.
        for name in ('DONCHIAN20_FILTER','DONCHIAN55_FILTER',
                     'EMA21_55_BOTH','EMA21_55_LONG','BB20_RSI_MEAN_REVERT',
                     'BTC_EMA20_PULLBACK'):
            if name=='BTC_EMA20_PULLBACK' and sym=='ETHUSDT':continue
            ev=eventmaps[name]
            item={}
            for label,lo,hi in splits:
                item[label]=report_window(bars,atrs,ev,lo,hi)
            # Includes unrealized marked position in return and normal
            # stress; reset 1000 USDT independently for every half.
            outputs[sym+':'+name]=item
            print('RESULT',sym,name,[(label,item[label]['pct'],item[label]['stress_pct'],
                                        item[label]['trades']) for label,_,_ in splits],flush=True)
    # One prespecified selector from DEVELOPMENT year 2025 ONLY:
    # least bad combination? If no positive net+stress in BOTH 2025 halves,
    # deliberately select CASH; cannot force an unverified winner.
    eligible=[]
    for key,val in outputs.items():
        h1=val['2025_H1'];h2=val['2025_H2']
        if (h1['pct']>0 and h2['pct']>0 and
            h1['stress_pct']>0 and h2['stress_pct']>0 and
            h1['trades']+h2['trades']>=8):
            eligible.append((key,h1['pct']+h2['pct'],
                             min(h1['stress_pct'],h2['stress_pct'])))
    eligible.sort(key=lambda x:(x[2],x[1]),reverse=True)
    candidate=eligible[0][0] if eligible else 'CASH - no robust candidate'
    print('SELECT_2025_ONLY',candidate,flush=True)
    print('ANALYSIS_COMPLETE_JSON',json.dumps({'2025_selector':candidate,
        'periods':splits,'models':outputs,
        'rules':{'fee_per_side':.0006,'slip_per_side':.0003,
                 'notional_max_x':1.0,'risk_fraction':.005,
                 'funding_included':False,
                 'historical_not_forward':True}},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
