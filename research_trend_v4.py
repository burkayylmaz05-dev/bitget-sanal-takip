# -*- coding: utf-8 -*-
"""Locked rules, causal 4H/1D trend-family research on Bitget futures.

No API keys, no order placement, no changing live alert bot.
720 UTC days: first 260 warm-up, next 230 development, last 230 holdout.
4H execution at NEXT 4H OPEN, full initial bar stop and trailing stops,
0.06% taker + 0.03% slippage each leg, stress at double costs.
NO funding/spread/market impact. A positive result is NOT proof.
"""
import bisect
import datetime as dt
import json
import math
import os
import time
from pathlib import Path

import research_backtest as core

ROOT=Path(__file__).resolve().parent
DAY=86400000
FOUR=4*3600000
DAYS=720
WARMUP=260
DEVELOP=230
EQUITY=1000.0
RISK=.005
ONE_X=1.0
METHODS=('BREAK20_LONG','BREAK55_LONG','BREAK20_BIDIR',
         'PULLBACK_LONG','PULLBACK_BIDIR','DAILY_BREAK20_LONG')
SYMS=('BTCUSDT','ETHUSDT')


def daily_candles(symbol,start,end):
    """UTC-aligned daily candle history, strict continuity and 200-bar cursor."""
    rows={}
    pointer=end
    calls=0
    while pointer>=start:
        packet=core.request({'symbol':symbol,'productType':'USDT-FUTURES',
                             'granularity':'1Dutc','limit':'200',
                             'endTime':str(pointer)})
        batch=[]
        for row in packet:
            try:
                r=(int(row[0]),)*(1) + tuple(float(x) for x in row[1:6])
                if all(math.isfinite(x) and x>0 for x in r[1:5]):
                    batch.append(r)
            except (ValueError,TypeError,IndexError):
                pass
        if not batch:
            break
        for r in batch:
            if start<=r[0] and r[0]+DAY<=end:
                rows[r[0]]=r
        earliest=min(r[0] for r in batch)
        if earliest>=pointer:
            raise RuntimeError('daily cursor stall')
        pointer=earliest
        calls+=1
        if calls>100:
            raise RuntimeError('daily pagination exceeded')
        time.sleep(.1)
    ordered=[rows[t] for t in sorted(rows)]
    if len(ordered)<min(DAYS-2,(end-start)//DAY-2):
        raise RuntimeError(f'daily bars missing {symbol}: {len(ordered)}')
    if any(b[0]-a[0]!=DAY for a,b in zip(ordered,ordered[1:])):
        raise RuntimeError('daily time gap')
    print(symbol,'UTC daily',len(ordered),'pages',calls,flush=True)
    return ordered


def ema(close,length):
    a=2/(length+1)
    out=[]
    v=None
    for p in close:
        v=p if v is None else v+a*(p-v)
        out.append(v)
    return out


def atr_history(rows,n=14):
    out=[]
    running=0.
    for i,r in enumerate(rows):
        prev=rows[i-1][4] if i else r[1]
        tr=max(r[2]-r[3],abs(r[2]-prev),abs(r[3]-prev))
        if i< n:
            running+=tr/n
        else:
            running=(running*(n-1)+tr)/n
        out.append(running)
    return out


def event_map(four,daily):
    """Generate all method signals only with bars closed at decision time."""
    close4=[r[4] for r in four]
    close_d=[r[4] for r in daily]
    times_d=[r[0] for r in daily]
    e20=ema(close4,20)
    e50=ema(close4,50)
    e100d=ema(close_d,100)
    e200d=ema(close_d,200)
    atr4=atr_history(four)
    out={k:{} for k in METHODS}
    for i in range(320,len(four)):
        r=four[i]
        decision=r[0]+FOUR
        # Most recent closed daily candle, not developing daily candle.
        j=bisect.bisect_right(times_d,decision-DAY)-1
        if j<220:
            continue
        dprice=close_d[j]
        d_slope=e100d[j]-e100d[j-15]
        if dprice>e100d[j]>e200d[j] and d_slope>0:
            trend=1
        elif dprice<e100d[j]<e200d[j] and d_slope<0:
            trend=-1
        else:
            trend=0
        last=close4[i]
        a=atr4[i]
        if a/last<.002 or a/last>.08:
            continue
        hi20=max(x[2] for x in four[i-20:i])
        lo20=min(x[3] for x in four[i-20:i])
        hi55=max(x[2] for x in four[i-55:i])
        lo55=min(x[3] for x in four[i-55:i])
        if last>hi20 and last-hi20<1.5*a:
            sign20=1
        elif last<lo20 and lo20-last<1.5*a:
            sign20=-1
        else:
            sign20=0
        if last>hi55 and last-hi55<1.5*a:
            sign55=1
        else:
            sign55=0
        crossed_up=close4[i-1]<=e20[i-1] and last>e20[i] and last>e50[i]
        crossed_down=close4[i-1]>=e20[i-1] and last<e20[i] and last<e50[i]
        proposal={
            'BREAK20_LONG':(1 if trend==1 and sign20==1 else 0,2.5,3.0),
            'BREAK55_LONG':(1 if trend==1 and sign55==1 else 0,3.0,3.5),
            'BREAK20_BIDIR':(sign20 if trend!=0 and sign20==trend else 0,2.5,3.0),
            'PULLBACK_LONG':(1 if trend==1 and crossed_up else 0,2.0,2.5),
            'PULLBACK_BIDIR':(trend if (trend==1 and crossed_up) or (trend==-1 and crossed_down) else 0,2.0,2.5),
        }
        if decision % DAY==0 and j>=220:
            # Daily breakout above prior 20 completed daily bars.
            prior=max(v[2] for v in daily[j-20:j])
            dailylong=int(trend==1 and dprice>prior)
            proposal['DAILY_BREAK20_LONG']=(dailylong,2.8,3.5)
        for name,(d,stop_mult,trail_mult) in proposal.items():
            if not d:
                continue
            out[name][decision]={
                'd':d,'ref':last,'stop':last-d*stop_mult*a,
                'atr':a,'trail_mult':trail_mult,'signal_time':decision
            }
    return out,atr4


def summarize(trades,curve,start,end):
    wins=[t['pnl'] for t in trades if t['pnl']>0]
    losses=[t['pnl'] for t in trades if t['pnl']<=0]
    equity=curve[-1]
    peak=EQUITY
    dd=0.
    for x in curve:
        peak=max(peak,x)
        dd=min(dd,x/peak-1)
    return {'days':(end-start)//DAY,'trades':len(trades),
            'wins':len(wins),
            'win_rate':round(100*len(wins)/len(trades),2) if trades else None,
            'profit_factor':round(sum(wins)/-sum(losses),3) if sum(losses)<0 else None,
            'return_pct':round(100*(equity/EQUITY-1),3),
            'net_usdt':round(equity-EQUITY,2),
            'max_drawdown_pct':round(100*dd,3),
            'example_trades':trades[:2]}


def simulate(four,events,atr4,start,end,fee=.0006,slip=.0003):
    capital=EQUITY
    trade=None
    deals=[]
    curve=[EQUITY]
    for i,r in enumerate(four):
        t,o,h,l,c,v=r
        if t<start or t>=end:
            continue
        was_open=trade is not None
        if was_open:
            p=trade
            d=p['d']
            stop_hit=l<=p['stop'] if d==1 else h>=p['stop']
            timed_out=t>=p['deadline']
            if stop_hit or timed_out:
                raw=(min(o,p['stop']) if d==1 else max(o,p['stop'])) if stop_hit else o
                exit_fill=raw*(1-d*slip)
                pnl=(exit_fill-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+exit_fill)
                capital+=pnl
                deals.append({'entry_utc':p['opened'],'exit_utc':t,'direction':d,
                              'pnl':round(pnl,6),
                              'reason':'STOP' if stop_hit else 'TIME'})
                trade=None
            else:
                # Update AFTER bar closes; new stop is active on NEXT bar.
                updated=c-d*p['trail']*atr4[i]
                p['stop']=max(p['stop'],updated) if d==1 else min(p['stop'],updated)
        if not was_open:
            event=events.get(t)
            if event and capital>0:
                d=event['d']
                entry=o*(1+d*slip)
                risk=(entry-event['stop'])*d
                if risk>0:
                    qty=min(capital*RISK/risk,capital*ONE_X/entry)
                    if qty>0:
                        trade={'d':d,'entry':entry,'stop':event['stop'],
                               'qty':qty,'trail':event['trail_mult'],'opened':t,
                               'deadline':t+30*DAY}
                        # Same entry bar may already reach stop. Stop first.
                        hit=l<=trade['stop'] if d==1 else h>=trade['stop']
                        if hit:
                            raw=min(o,trade['stop']) if d==1 else max(o,trade['stop'])
                            exit_fill=raw*(1-d*slip)
                            pnl=(exit_fill-entry)*d*qty-fee*qty*(entry+exit_fill)
                            capital+=pnl
                            deals.append({'entry_utc':t,'exit_utc':t,'direction':d,
                                          'pnl':round(pnl,6),'reason':'STOP_ENTRY_BAR'})
                            trade=None
        if trade:
            p=trade
            # Estimate remaining close cost for drawdown, no next bar foresight.
            mark=c*(1-p['d']*slip)
            marked=capital+(mark-p['entry'])*p['d']*p['qty']-fee*(p['entry']+mark)*p['qty']
            curve.append(marked)
        else:
            curve.append(capital)
    if trade:
        last=max((r for r in four if start<=r[0]<end),key=lambda r:r[0],default=None)
        if last:
            p=trade
            raw=last[4]
            fill=raw*(1-p['d']*slip)
            pnl=(fill-p['entry'])*p['d']*p['qty']-fee*p['qty']*(p['entry']+fill)
            capital+=pnl
            deals.append({'entry_utc':p['opened'],'exit_utc':last[0],
                          'direction':p['d'],'pnl':round(pnl,6),'reason':'WINDOW_END'})
            curve.append(capital)
    return summarize(deals,curve,start,end)


def benchmark_long(four,start,end,fee=.0006,slip=.0003):
    sample=[x for x in four if start<=x[0]<end]
    if not sample:
        return None
    buy=sample[0][1]*(1+slip)
    sell=sample[-1][4]*(1-slip)
    # One unit of equity buys <=1x notional
    qty=EQUITY/buy
    fees=fee*qty*(buy+sell)
    pnl=(sell-buy)*qty-fees
    return round(100*pnl/EQUITY,3)


def main():
    end=int(time.time()*1000)//DAY*DAY
    start=end-DAYS*DAY
    dev=start+WARMUP*DAY
    validation=dev+DEVELOP*DAY
    result={
      'completed':False,'start_utc':dt.datetime.fromtimestamp(start/1000,dt.timezone.utc).isoformat(),
      'development_utc':dt.datetime.fromtimestamp(dev/1000,dt.timezone.utc).isoformat(),
      'holdout_utc':dt.datetime.fromtimestamp(validation/1000,dt.timezone.utc).isoformat(),
      'end_utc':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
      'methods':list(METHODS),
      'assumptions':{'source':'Bitget USDT-FUTURES actual historical 4H + 1Dutc candles',
                     'taker_fee_each_side':.0006,'adverse_slippage_each_side':.0003,
                     'stress_fee':.0012,'stress_slippage':.0006,
                     'same_bar_stop_first':True,'next_4h_open_entry':True,
                     '1x_notional_cap':True,'risk_per_entry':RISK,'max_hold_days':30,
                     'funding_included':False,'spread_dynamic_included':False,
                     'market_impact_included':False,'live_executions':False,
                     'selection':'none; all predefined outcomes including losers published'},
      'results':{},'buy_hold_reference':{},'data_checks':{},'errors':[]}
    for symbol in SYMS:
        try:
            four,pages=core.history(symbol,'4H',start,end)
            days=daily_candles(symbol,start,end)
            ev,atr4=event_map(four,days)
            result['data_checks'][symbol]={'4h_bars':len(four),'1Dutc_bars':len(days),
                      '4h_pages':pages,'last_4h':four[-1][0],'last_daily':days[-1][0]}
            for part,a,b in [('development',dev,validation),('holdout',validation,end)]:
                result['buy_hold_reference'][symbol+':'+part]=benchmark_long(four,a,b)
            for method in METHODS:
                res={}
                for part,a,b in [('development',dev,validation),('holdout',validation,end)]:
                    res[part]=simulate(four,ev[method],atr4,a,b)
                    res[part+'_double_costs']=simulate(four,ev[method],atr4,a,b,fee=.0012,slip=.0006)
                result['results'][symbol+':'+method]=res
                print('STRATEGY',symbol,method,
                      'development',res['development']['return_pct'],
                      'holdout',res['holdout']['return_pct'],
                      'stress',res['holdout_double_costs']['return_pct'],
                      'trades',res['holdout']['trades'],flush=True)
        except Exception as exc:
            msg=f'{symbol} {type(exc).__name__}: {str(exc)[:250]}'
            result['errors'].append(msg)
            print('ERROR',msg,flush=True)
    result['completed']=not result['errors'] and len(result['results'])==len(METHODS)*len(SYMS)
    shortlisted=[]
    for key,r in result['results'].items():
        d=r['development'];v=r['holdout'];st=r['holdout_double_costs']
        if (d['return_pct']>0 and v['return_pct']>3 and st['return_pct']>0
            and v['trades']>=15 and v['profit_factor'] is not None
            and v['profit_factor']>=1.25 and v['max_drawdown_pct']>=-10):
            shortlisted.append(key)
    result['shortlist_for_more_testing']=shortlisted
    (ROOT/'research_trend_v4_report.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print('FINAL',result['completed'],'shortlist',shortlisted,'errors',result['errors'],flush=True)
    if not result['completed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
