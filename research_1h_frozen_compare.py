# -*- coding: utf-8 -*-
"""FROZEN candidate comparison of BTC/ETH 1H paper trading strategies.

600 full UTC days of genuine Bitget USDT-FUTURES candles:
100-day warmup, 250-day development, 250-day untouched final validation.
4 different 1H strategies, all costs and losing trials disclosed.
Decisions from CLOSED 1H bars ONLY, next hour open, same bar stop first,
intrabar stop/target pessimism, funding unavailable (not included).
No exchange keys, Telegram, trades, or user's local state.
"""
import datetime as dt
import json
import math
import time

import research_backtest as core
import bitget_sinyal_takip as indicators

HOUR=3_600_000
DAY=86_400_000
DAYS=600
WARMUP_DAYS=100
DEV_DAYS=250
START=1000.0
RISK=.005
NOTIONAL=1.0
FEE=.0006
SLIP=.0003
SYMBOLS=('BTCUSDT','ETHUSDT')
METHODS=('EMA20_RECLAIM','DONCHIAN55','DONCHIAN20','RSI_PULLBACK')


def ema(xs,n):
    return indicators.ema_series(xs,n)


def atr_series(rows,n=14):
    out=[None]*len(rows)
    tr=[]
    for i in range(1,len(rows)):
        b=rows[i]
        p=rows[i-1][4]
        tr.append(max(b[2]-b[3],abs(b[2]-p),abs(b[3]-p)))
        if len(tr)==n:
            out[i]=sum(tr)/n
        elif len(tr)>n:
            out[i]=(out[i-1]*(n-1)+tr[-1])/n
    return out


def rsi_series(closes,n=14):
    out=[50.0]*len(closes)
    gains=losses=0.
    for i in range(1,len(closes)):
        ch=closes[i]-closes[i-1]
        if i<=n:
            gains+=max(ch,0)
            losses+=max(-ch,0)
            if i==n:
                gains/=n
                losses/=n
        else:
            gains=(gains*(n-1)+max(ch,0))/n
            losses=(losses*(n-1)+max(-ch,0))/n
            out[i]=100. if losses==0 and gains>0 else 50. if gains==losses==0 else 100.-100./(1+gains/losses)
    return out


def features(rows):
    closes=[r[4] for r in rows]
    return {'closes':closes, 'ema20':ema(closes,20),
            'ema50':ema(closes,50),'ema200':ema(closes,200),
            'atr':atr_series(rows),'rsi':rsi_series(closes)}


def signal(rows, f, i, method):
    if i<max(280,55) or f['atr'][i] is None:
        return None
    c=f['closes'][i]
    a=f['atr'][i]
    if not(.001<a/c<.055):
        return None
    e20=f['ema20'][i];e50=f['ema50'][i];e200=f['ema200'][i]
    up=e50>e200 and e50>f['ema50'][i-24] and c>e200
    down=e50<e200 and e50<f['ema50'][i-24] and c<e200
    d=0
    stop_mult=2.0
    trail_mult=2.8
    target_mult=None
    timeout=120
    if method=='EMA20_RECLAIM':
        upcross=f['closes'][i-1]<=f['ema20'][i-1] and c>e20
        downcross=f['closes'][i-1]>=f['ema20'][i-1] and c<e20
        d=1 if up and upcross else -1 if down and downcross else 0
        stop_mult=2.1;trail_mult=2.8;timeout=96
    elif method=='DONCHIAN55':
        high=max(x[2] for x in rows[i-55:i])
        low=min(x[3] for x in rows[i-55:i])
        d=1 if up and c>high and c-high<1.5*a else -1 if down and c<low and low-c<1.5*a else 0
        stop_mult=2.7;trail_mult=3.2;timeout=168
    elif method=='DONCHIAN20':
        high=max(x[2] for x in rows[i-20:i])
        low=min(x[3] for x in rows[i-20:i])
        d=1 if up and c>high and c-high<1.0*a else -1 if down and c<low and low-c<1.0*a else 0
        stop_mult=2.2;trail_mult=2.6;timeout=120
    elif method=='RSI_PULLBACK':
        # Trend-continuation after short-term oversold/overbought + turn.
        d=1 if up and f['rsi'][i-1]<35 and f['rsi'][i]>38 else -1 if down and f['rsi'][i-1]>65 and f['rsi'][i]<62 else 0
        stop_mult=2.0;trail_mult=None;target_mult=3.0;timeout=48
    if not d:
        return None
    return {'direction':d,'ref':c,'atr':a,'stopmult':stop_mult,'trailmult':trail_mult,
            'targetmult':target_mult,'timeout':timeout}


def run(rows,f,method,start,end,fee=FEE,slip=SLIP):
    equity=START
    open_trade=None
    peak=START
    worst_dd=0.
    deals=[]
    equity_curve=[START]
    # Use prior bar to decide at current hour open, then simulate current
    # candle for existing or newly opened position. No future OHLC for entry.
    for i in range(281,len(rows)):
        t,o,h,l,c,_vol=rows[i]
        if t<start or t>=end:
            continue
        proposal=signal(rows,f,i-1,method)
        was_open=open_trade is not None
        if not was_open and proposal and equity>0:
            d=proposal['direction']
            # Prevent entries after excessive opening gap
            if abs(o-proposal['ref'])<=.5*proposal['atr']:
                entry=o*(1+d*slip)
                stop=proposal['ref']-d*proposal['stopmult']*proposal['atr']
                target=None if proposal['targetmult'] is None else (
                    proposal['ref']+d*proposal['targetmult']*proposal['atr'])
                if (entry-stop)*d>0 and (target is None or (target-entry)*d>0):
                    qty=min(equity*RISK/((entry-stop)*d),equity*NOTIONAL/entry)
                    if qty>0:
                        open_trade={'d':d,'entry':entry,'stop':stop,
                                    'target':target,'qty':qty,
                                    'opened':t,'trail':proposal['trailmult'],
                                    'deadline':t+proposal['timeout']*HOUR}
        if open_trade:
            p=open_trade
            d=p['d']
            stop_hit=l<=p['stop'] if d==1 else h>=p['stop']
            target_hit=p['target'] is not None and (h>=p['target'] if d==1 else l<=p['target'])
            timed=t>=p['deadline']
            reason=None
            if stop_hit:
                raw=min(o,p['stop']) if d==1 else max(o,p['stop'])
                reason='STOP'
            elif target_hit:
                raw=p['target']
                reason='TARGET'
            elif timed:
                raw=o
                reason='TIME'
            if reason:
                exitfill=raw*(1-d*slip)
                pnl=(exitfill-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+exitfill)
                equity+=pnl
                deals.append({'entry_ms':p['opened'],'exit_ms':t,'direction':d,
                              'pnl':round(pnl,6),'reason':reason,
                              'entry':round(p['entry'],4),
                              'exit':round(exitfill,4)})
                open_trade=None
            elif p['trail'] is not None:
                # Trailing stop updated with information at the end of current
                # 1H candle; new stop is active from NEXT candle only.
                candidate=c-d*p['trail']*f['atr'][i]
                p['stop']=max(p['stop'],candidate) if d==1 else min(p['stop'],candidate)
        if open_trade:
            p=open_trade
            mark=c*(1-p['d']*slip)
            marked=equity+(mark-p['entry'])*p['d']*p['qty']-fee*p['qty']*(p['entry']+mark)
        else:
            marked=equity
        peak=max(peak,marked)
        worst_dd=min(worst_dd,100*(marked/peak-1))
        equity_curve.append(marked)
    # Mark the current open trade to market and include unrealized net result
    # for honest period outcome; do not incorrectly label it 'closed'.
    unreal=None
    if open_trade:
        p=open_trade
        last=next((r for r in reversed(rows) if start<=r[0]<end),None)
        if last:
            exitmark=last[4]*(1-p['d']*slip)
            unreal=(exitmark-p['entry'])*p['d']*p['qty']-fee*p['qty']*(p['entry']+exitmark)
    net=equity-START+(unreal or 0.)
    wins=[v for v in deals if v['pnl']>0]
    losses=[v for v in deals if v['pnl']<=0]
    profit=sum(v['pnl'] for v in wins)
    loss=-sum(v['pnl'] for v in losses)
    return {
        'closed':len(deals),'wins':len(wins),'losses':len(losses),
        'win_rate':round(len(wins)*100/len(deals),2) if deals else None,
        'profit_factor':round(profit/loss,3) if loss else None,
        'closed_net_usdt':round(equity-START,3),
        'open_marked_pnl_usdt':round(unreal,3) if unreal is not None else None,
        'net_including_open_pct':round(net/START*100,3),
        'max_marked_drawdown_pct':round(worst_dd,3),
        'examples':deals[:3],
    }


def main():
    end=int(time.time()*1000)//DAY*DAY
    start=end-DAYS*DAY
    development=start+WARMUP_DAYS*DAY
    holdout=development+DEV_DAYS*DAY
    report={'end_utc':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
            'warmup_end_utc':dt.datetime.fromtimestamp(development/1000,dt.timezone.utc).isoformat(),
            'holdout_start_utc':dt.datetime.fromtimestamp(holdout/1000,dt.timezone.utc).isoformat(),
            'symbols':SYMBOLS,'methods':METHODS,'results':{},'data_errors':[],
            'assumptions':{'each_side_fee':FEE,'each_side_slippage':SLIP,
                           'max_notional_x':NOTIONAL,'risk_fraction':RISK,
                           'funding_included':False,'live_execution':False,
                           'next_candle_open_entry':True,'same_bar_stop_first':True,
                           'no_future_price_for_signals':True}}
    for sym in SYMBOLS:
        try:
            candles,pages=core.history(sym,'1H',start,end)
            f=features(candles)
            print('DATA',sym,'bars',len(candles),'pages',pages,flush=True)
            for method in METHODS:
                dev=run(candles,f,method,development,holdout)
                val=run(candles,f,method,holdout,end)
                stress=run(candles,f,method,holdout,end,fee=FEE*2,slip=SLIP*2)
                report['results'][sym+':'+method]={
                    'development':dev,'holdout':val,'holdout_double_cost':stress}
                print('RESULT',sym,method,'dev',dev['net_including_open_pct'],
                      'holdout',val['net_including_open_pct'],
                      'double_cost',stress['net_including_open_pct'],
                      'n_holdout',val['closed'],flush=True)
        except Exception as exc:
            text=f'{sym} {type(exc).__name__}: {str(exc)[:300]}'
            report['data_errors'].append(text)
            print('ERROR',text,flush=True)
    # First rank all methods by development only. This identifies a candidate
    # without peeking into holdout. Publish every candidate's holdout anyway.
    chosen=sorted(
        ((name,values['development']) for name,values in report['results'].items()
         if values['development']['closed']>=20),
        key=lambda x:(x[1]['net_including_open_pct'],
                      x[1]['max_marked_drawdown_pct']),reverse=True)
    report['selected_by_development_only']=chosen[0][0] if chosen else None
    print('SELECTED_FROM_DEV',report['selected_by_development_only'],flush=True)
    if report['selected_by_development_only']:
        x=report['results'][report['selected_by_development_only']]
        print('HONEST_HOLDOUT',json.dumps(x['holdout'],ensure_ascii=False),flush=True)
    print('FULL_RESEARCH_JSON',json.dumps(report,ensure_ascii=False),flush=True)
    if report['data_errors']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
