# -*- coding: utf-8 -*-
"""Specific 2026 BTC/ETH 4H strategy audit -- frozen rules and honest validation.

External hypothesis classes:
 - 4H EMA21/55 trend following (CoinQuant published 2026 research)
 - Donchian20/55 trend breakouts incl trend filter (Quattro inspired; NO PYRAMID)
 - BB20 2sigma RSI mean reversion in ranging markets
 - Original BTC PULLBACK_BIDIR 4h for a grounded benchmark.
All trades are fictional historical simulations, no Bitget order endpoints.
2026 Jan1-May31 development; 2026 Jun1-Oct10 validation; 2025 warm-up.
1,000 USDT initial EACH symbol/strategy/window, max 1x notional,
0.06% taker + 0.03% adverse slip per SIDE (stress 2x).
Intrabar stop first; trailing changes effective following candle only.
No funding, exact orderbook/spread, leverage liquidations or forward execution.
"""
import bisect
import datetime as dt
import json
import math
import statistics
import time

import research_backtest as data
import research_trend_v4 as previous

HOUR=3600000
FOUR=4*HOUR
DAY=24*HOUR
START=1000.0
METHODS=('EMA21_55_LONG','EMA21_55_BOTH','DONCHIAN20_FILTER','DONCHIAN55_FILTER','BB20_RSI_MEAN_REVERT','BTC_EMA20_PULLBACK')
SYMS=('BTCUSDT','ETHUSDT')


def emaseries(x,p):
    a=2/(p+1)
    out=[]
    prev=x[0]
    for item in x:
        prev=prev+a*(item-prev)
        out.append(prev)
    return out


def atrseries(rows,p=14):
    ans=[]
    x=None
    for i,(_,o,h,l,c,vol) in enumerate(rows):
        last=rows[i-1][4] if i else o
        tr=max(h-l,abs(h-last),abs(l-last))
        x=tr if x is None else (x*(p-1)+tr)/p
        ans.append(x)
    return ans


def rsiseries(x,p=14):
    gains=losses=0.
    ans=[50.0]*len(x)
    for i in range(1,len(x)):
        delta=x[i]-x[i-1]
        if i<=p:
            gains+=max(delta,0)
            losses+=max(-delta,0)
            if i==p:
                gains/=p
                losses/=p
        else:
            gains=(gains*(p-1)+max(delta,0))/p
            losses=(losses*(p-1)+max(-delta,0))/p
            ans[i]=(100 if losses==0 and gains>0 else 50 if gains==losses==0
                    else 100-100/(1+gains/losses))
    return ans


def build_events(rows,daily):
    closes=[r[4] for r in rows]
    dcloses=[r[4] for r in daily]
    em21,em55,em50=[emaseries(closes,n) for n in (21,55,50)]
    ed200,ed100=[emaseries(dcloses,n) for n in (200,100)]
    atr=atrseries(rows)
    rsi=rsiseries(closes)
    daily_times=[r[0] for r in daily]
    results={key:{} for key in METHODS}
    for i in range(400,len(rows)):
        bar=rows[i]
        t=bar[0]
        decision=t+FOUR
        # latest day completely closed by this decision, NEVER current daily
        j=bisect.bisect_right(daily_times,decision-DAY)-1
        if j<225:
            continue
        c=closes[i]
        a=atr[i]
        if not(.001 < a/c < .08):
            continue
        daily_up=ed100[j]>ed200[j] and ed100[j]>ed100[j-15] and dcloses[j]>ed100[j]
        daily_down=ed100[j]<ed200[j] and ed100[j]<ed100[j-15] and dcloses[j]<ed100[j]
        daily_over200=dcloses[j]>ed200[j]
        daily_under200=dcloses[j]<ed200[j]
        prev_spread=em21[i-1]-em55[i-1]
        new_spread=em21[i]-em55[i]
        longcross=prev_spread<=0 and new_spread>0
        shortcross=prev_spread>=0 and new_spread<0
        # EMA21/55 cross. Simple long-only is flat below 55 / never shorts.
        if longcross and daily_over200:
            results['EMA21_55_LONG'][decision]=dict(d=1,stop=c-2.5*a,atr=a,trail=2.5,timeout=60*DAY)
        if longcross and daily_over200:
            results['EMA21_55_BOTH'][decision]=dict(d=1,stop=c-2.5*a,atr=a,trail=2.5,timeout=60*DAY)
        elif shortcross and daily_under200:
            results['EMA21_55_BOTH'][decision]=dict(d=-1,stop=c+2.5*a,atr=a,trail=2.5,timeout=60*DAY)
        high20=max(r[2] for r in rows[i-20:i])
        low20=min(r[3] for r in rows[i-20:i])
        high55=max(r[2] for r in rows[i-55:i])
        low55=min(r[3] for r in rows[i-55:i])
        for name,up,down in [('DONCHIAN20_FILTER',high20,low20),('DONCHIAN55_FILTER',high55,low55)]:
            if daily_up and c>up and c-up<=1.5*a:
                results[name][decision]=dict(d=1,stop=c-2.5*a,atr=a,trail=3,timeout=30*DAY)
            elif daily_down and c<down and down-c<=1.5*a:
                results[name][decision]=dict(d=-1,stop=c+2.5*a,atr=a,trail=3,timeout=30*DAY)
        prior20=closes[i-19:i+1]
        mid=sum(prior20)/len(prior20)
        sd=statistics.pstdev(prior20)
        # Only fade prices when daily trend is not strong in same direction,
        # and 4H EMA trend is flat enough. Protect against strong trend melts.
        flat=abs(em55[i]-em55[i-12])/c<.015
        if flat and sd>0:
            if c<mid-2*sd and rsi[i]<33 and not daily_down:
                results['BB20_RSI_MEAN_REVERT'][decision]=dict(d=1,stop=c-2*a,
                    target=mid,atr=a,trail=None,timeout=3*DAY)
            elif c>mid+2*sd and rsi[i]>67 and not daily_up:
                results['BB20_RSI_MEAN_REVERT'][decision]=dict(d=-1,stop=c+2*a,
                    target=mid,atr=a,trail=None,timeout=3*DAY)
    # Import unchanged published predecessor for benchmark. No rule edits.
    old,_=previous.event_map(rows,daily)
    results['BTC_EMA20_PULLBACK']=old['PULLBACK_BIDIR']
    return results,atr


def simulate(rows,events,atr,start,end,fee=.0006,slip=.0003):
    balance=START
    position=None
    curve=[START]
    trades=[]
    peak=START
    worst=0.
    for i,bar in enumerate(rows):
        t,o,h,l,c,_v=bar
        if not start<=t<end:
            continue
        was_open=position is not None
        if position:
            p=position;d=p['d']
            stop=(l<=p['stop']) if d==1 else (h>=p['stop'])
            tgt=p.get('target')
            take=(h>=tgt if d==1 else l<=tgt) if tgt is not None else False
            timed=t>=p['deadline']
            exit_raw=None;why=None
            if stop:
                exit_raw=min(o,p['stop']) if d==1 else max(o,p['stop'])
                why='STOP'
            elif take:
                exit_raw=tgt;why='TARGET'
            elif timed:
                exit_raw=o;why='TIME'
            if why:
                fill=exit_raw*(1-d*slip)
                pnl=(fill-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+fill)
                balance+=pnl
                trades.append(dict(open_utc=p['opened'],exit_utc=t,dir=d,pnl=round(pnl,4),
                                   entry=round(p['entry'],2),exit=round(fill,2),reason=why))
                position=None
            elif p['trail'] is not None:
                updated=c-d*p['trail']*atr[i]
                p['stop']=max(p['stop'],updated) if d==1 else min(p['stop'],updated)
        if not was_open and balance>0 and t in events:
            ev=events[t];d=ev['d']
            entry=o*(1+d*slip)
            risk=(entry-ev['stop'])*d
            reference=ev.get('ref',ev.get('reference',None))
            # bar open gap guard against chasing stale close
            if risk>0 and abs(entry-ev.get('ref',o))<=2.0*ev['atr']:
                tgt=ev.get('target')
                if tgt is None or (tgt-entry)*d>0:
                    qty=min(balance*.005/risk,balance/entry)
                    if qty>0:
                        position=dict(d=d,entry=entry,qty=qty,stop=ev['stop'],
                                      target=tgt,trail=ev.get('trail',ev.get('trail_mult')),
                                      opened=t,deadline=t+ev.get('timeout',30*DAY))
                        # Full initial bar stop/target, stop-first.
                        hit=l<=position['stop'] if d==1 else h>=position['stop']
                        hit_tgt=tgt is not None and (h>=tgt if d==1 else l<=tgt)
                        if hit or hit_tgt:
                            raw=(min(o,position['stop']) if d==1 else max(o,position['stop'])) if hit else tgt
                            x=raw*(1-d*slip)
                            pnl=(x-entry)*d*qty-fee*qty*(entry+x)
                            balance+=pnl
                            trades.append(dict(open_utc=t,exit_utc=t,dir=d,
                                pnl=round(pnl,4),entry=round(entry,2),exit=round(x,2),
                                reason='STOP_ENTRY' if hit else 'TARGET_ENTRY'))
                            position=None
        if position:
            p=position;d=p['d']
            mark=c*(1-d*slip)
            equity=balance+(mark-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+mark)
        else:
            equity=balance
        peak=max(peak,equity)
        worst=min(worst,100*(equity/peak-1))
        curve.append(equity)
    unreal=0.
    if position:
        last=next((r for r in reversed(rows) if start<=r[0]<end),None)
        if last:
            p=position;d=p['d']
            mark=last[4]*(1-d*slip)
            unreal=(mark-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+mark)
    pfpos=sum(z['pnl'] for z in trades if z['pnl']>0)
    pfneg=-sum(z['pnl'] for z in trades if z['pnl']<=0)
    return {
      'net_pct':round(100*(balance+unreal)/START-100,3),
      'closed_net_pct':round(100*balance/START-100,3),
      'max_dd_pct':round(worst,3),
      'trades':len(trades),
      'wins':sum(z['pnl']>0 for z in trades),
      'profit_factor':round(pfpos/pfneg,3) if pfneg>0 else None,
      'open_at_end':bool(position),
      'recent_closed':trades[-3:]
    }


def main():
    end=int(time.time()*1000)//DAY*DAY
    start=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)
    sep=dt.datetime(2026,6,1,tzinfo=dt.timezone.utc)
    jan=int(start.timestamp()*1000);jun=int(sep.timestamp()*1000)
    begin=dt.datetime(2025,1,1,tzinfo=dt.timezone.utc)
    begin_ms=int(begin.timestamp()*1000)
    results={}
    for symbol in SYMS:
        try:
            four,ncalls=data.history(symbol,'4H',begin_ms,end)
            daily=previous.daily_candles(symbol,begin_ms,end)
            events,atr=build_events(four,daily)
            print('FETCH',symbol,'4H',len(four),'DAILY',len(daily),flush=True)
            for method in METHODS:
                if method=='BTC_EMA20_PULLBACK' and symbol!='BTCUSDT':
                    continue
                events_m=events[method]
                r1=simulate(four,events_m,atr,jan,jun)
                r2=simulate(four,events_m,atr,jun,end)
                r2stress=simulate(four,events_m,atr,jun,end,fee=.0012,slip=.0006)
                results[symbol+':'+method]={
                    '2026_JAN_MAY':r1,
                    '2026_JUN_OCT':r2,
                    '2026_JUN_OCT_COST_X2':r2stress
                }
                print('RESULT',symbol,method,'train',r1['net_pct'],
                      'holdout',r2['net_pct'],'2xcost',r2stress['net_pct'],
                      'testtrades',r2['trades'],flush=True)
        except Exception as exc:
            print('ERROR',symbol,type(exc).__name__,str(exc)[:350],flush=True)
            raise
    # Rank by Jan-May only; do not cherry pick Jun-Oct results.
    choices=sorted(((k,v) for k,v in results.items()
        if v['2026_JAN_MAY']['trades']>=5),
        key=lambda kv:kv[1]['2026_JAN_MAY']['net_pct'],reverse=True)
    winner=choices[0][0] if choices else None
    print('DEVELOPMENT_WINNER',winner,flush=True)
    print('ALL_RESULTS_JSON',json.dumps({'development':'2026-01-01 to 2026-06-01',
         'holdout':'2026-06-01 to '+dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).date().isoformat(),
         'selected_by_development_only':winner,'results':results,
         'fee_each_side':.0006,'slippage_each_side':.0003,
         'live_executions':False,'funding_included':False,
         'historical_not_forward':True},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
