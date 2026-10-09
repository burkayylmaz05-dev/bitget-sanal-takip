# -*- coding: utf-8 -*-
"""A/B research: pre-declared strategy families on Bitget BTC/ETH actual futures data.

No orders, no API keys, no tuning on validation window.
5m OHLC execution, taker fee each side, adverse slippage each side,
stop first on ambiguous bars including entry bar. Funding not included.
"""
import bisect
import collections
import datetime as dt
import json
import math
import os
import statistics
import time
from pathlib import Path
import research_backtest as bt

ROOT = Path(__file__).resolve().parent
MS = {'5m':300_000,'15m':900_000,'1H':3_600_000,'4H':14_400_000}
SYMBOLS=('BTCUSDT','ETHUSDT')
DAYS = int(os.getenv('ALT_RESEARCH_DAYS','240'))
WARMUP_DAYS = 50
TRAIN_DAYS = 100
SPLIT_NAMES=('development','validation')
FEE=0.0006
SLIP=0.0003
MAX_NOTIONAL=1.0
FRACTION_RISK=0.005
START=1000.0

# Fixed candidate list, chosen a priori from different classes.
METHODS = (
    'H1_CHANNEL20',
    'H1_CHANNEL55',
    'H1_PULLBACK_EMA20',
    'H1_BB_REVERSION',
    'H4_CHANNEL20',
    'H4_EMA_TREND',
    'M15_OVERSOLD_TREND',
)

def rolling_mean_std(closes,n=20):
    means=[None]*len(closes)
    stdevs=[None]*len(closes)
    s=ss=0.0
    for i,value in enumerate(closes):
        s+=value; ss+=value*value
        if i>=n:
            v=closes[i-n]
            s-=v;ss-=v*v
        if i>=n-1:
            avg=s/n
            means[i]=avg
            stdevs[i]=math.sqrt(max(0,ss/n-avg*avg))
    return means,stdevs

def features(rows):
    f=bt.indicator(rows)
    close=f['closes']
    f['ema20']=bt.ema(close,20)
    f['ema50']=bt.ema(close,50)
    f['ema200']=bt.ema(close,200)
    f['mean20'], f['std20']=rolling_mean_std(close,20)
    f['time']=[x[0] for x in rows]
    return f

def htf_index(times,decision,period):
    """A higher bar must be fully closed at the event timestamp."""
    return bisect.bisect_right(times,decision-period)-1

def regime(h4,index):
    """4h EMA50>EMA200 and close above EMA200; opposite for short."""
    if index<220:
        return 0
    close=h4['closes'][index]
    e50=h4['ema50'][index]
    e200=h4['ema200'][index]
    slope=h4['ema200'][index]-h4['ema200'][index-12]
    if close>e200 and e50>e200 and slope>0:
        return 1
    if close<e200 and e50<e200 and slope<0:
        return -1
    return 0

def make_signal(symbol,method,rows,i,features_tf,features_h4,jh4):
    if i<220 or jh4<220:
        return None
    bar=rows[i]
    close=bar[4]; atr=features_tf['atr'][i]
    if not close or not atr or not (0.0015 < atr/close < .065):
        return None
    closes=features_tf['closes']
    rsi=features_tf['rsi'][i]
    prior=rows[max(0,i-55):i]
    if len(prior)<55:
        return None
    higher=regime(features_h4,jh4)
    dir_=0
    stop=target=0.0
    tp_atr=stop_atr=0.0
    max_hold_hours=0
    tf='15m' if method.startswith('M15') else '4H' if method.startswith('H4') else '1H'

    if method.startswith('H1_CHANNEL') or method=='H4_CHANNEL20':
        length=55 if method=='H1_CHANNEL55' else 20
        bound=rows[i-length:i]
        high=max(r[2] for r in bound)
        low=min(r[3] for r in bound)
        # Do not chase candles where close overshot channel by multiple ATR.
        if close>high and close-high<1.2*atr:
            dir_=1
        elif close<low and low-close<1.2*atr:
            dir_=-1
        if tf=='1H' and (higher != dir_ or higher==0):
            return None
        if tf=='4H':
            if dir_==1 and not features_tf['ema50'][i]>features_tf['ema200'][i]:
                return None
            if dir_==-1 and not features_tf['ema50'][i]<features_tf['ema200'][i]:
                return None
        if not (dir_ and 38<=rsi<=78 if dir_==1 else 22<=rsi<=62):
            return None
        stop_atr=2.4 if length==55 else 2.0
        tp_atr=5.0 if length==55 else 4.0
        max_hold_hours=168 if tf=='4H' else 96

    elif method=='H1_PULLBACK_EMA20':
        # Only if market trend is persistent on 4H.
        if higher==0:
            return None
        e=features_tf['ema20']
        e50=features_tf['ema50'][i]
        e200=features_tf['ema200'][i]
        dir_=higher
        if dir_==1:
            qualifies=closes[i-1]<=e[i-1] and close>e[i] and close>e200 and e50>e200 and 46<=rsi<=68
        else:
            qualifies=closes[i-1]>=e[i-1] and close<e[i] and close<e200 and e50<e200 and 32<=rsi<=54
        if not qualifies:
            return None
        stop_atr=1.8;tp_atr=3.6;max_hold_hours=60

    elif method=='H1_BB_REVERSION':
        # Only calm, sideways 4H markets; rejection of +/- 2 stdev band.
        if higher!=0 or abs(features_h4['ema50'][jh4]/features_h4['ema200'][jh4]-1)>.025:
            return None
        means=features_tf['mean20'];stds=features_tf['std20']
        mean=means[i]; sd=stds[i]; prevmean=means[i-1]; prevsd=stds[i-1]
        if not mean or not sd or not prevmean or not prevsd:
            return None
        if closes[i-1]<prevmean-2*prevsd and close>mean-2*sd and rsi<48:
            dir_=1
        elif closes[i-1]>prevmean+2*prevsd and close<mean+2*sd and rsi>52:
            dir_=-1
        if not dir_:
            return None
        stop_atr=1.5
        stop=close-dir_*stop_atr*atr
        target=mean
        if (target-close)*dir_<0.6*atr:
            return None
        max_hold_hours=36

    elif method=='H4_EMA_TREND':
        e20=features_tf['ema20'];e50=features_tf['ema50'];e200=features_tf['ema200']
        if closes[i-1]<=e20[i-1] and close>e20[i] and e20[i]>e50[i]>e200[i] and 48<=rsi<=72:
            dir_=1
        elif closes[i-1]>=e20[i-1] and close<e20[i] and e20[i]<e50[i]<e200[i] and 28<=rsi<=52:
            dir_=-1
        if not dir_:
            return None
        stop_atr=2.2;tp_atr=4.4;max_hold_hours=168

    elif method=='M15_OVERSOLD_TREND':
        if higher==0:
            return None
        e=features_tf['ema20']; e50=features_tf['ema50'];e200=features_tf['ema200']
        dir_=higher
        if dir_==1:
            qualifies=closes[i-1]<e[i-1] and close>e[i] and e50[i]>e200[i] and rsi<62
        else:
            qualifies=closes[i-1]>e[i-1] and close<e[i] and e50[i]<e200[i] and rsi>38
        if not qualifies:
            return None
        stop_atr=1.6;tp_atr=3.2;max_hold_hours=18
    else:
        raise ValueError(method)
    if not dir_:
        return None
    if method!='H1_BB_REVERSION':
        stop=close-dir_*stop_atr*atr
        target=close+dir_*tp_atr*atr
    if (close-stop)*dir_<=0 or (target-close)*dir_<=0:
        return None
    return {'time':bar[0]+MS[tf],'direction':dir_,
            'stop':stop,'target':target,'frame':tf,'timeout':max_hold_hours*3_600_000,
            'reference':close,'atr':atr,'method':method,'symbol':symbol}

def summarize(trades,start,end,curve):
    wins=[t['pnl'] for t in trades if t['pnl']>0]
    losses=[t['pnl'] for t in trades if t['pnl']<=0]
    pf=round(sum(wins)/(-sum(losses)),3) if sum(losses)<0 else None
    balance=curve[-1] if curve else START
    hi=START; maxdd=0.0
    for bal in curve:
        hi=max(hi,bal); maxdd=min(maxdd,bal/hi-1)
    return {'days':round((end-start)/86_400_000,1),
            'trades':len(trades),'wins':len(wins),
            'win_rate_pct':round(len(wins)/len(trades)*100,2) if trades else None,
            'net_usdt':round(balance-START,2),
            'return_pct':round((balance/START-1)*100,3),
            'profit_factor':pf,'max_drawdown_pct':round(maxdd*100,3)}

def evaluate(five,events,start_ms,end_ms):
    """Independent 1000 USDT virtual account, 5m bar next-open fills."""
    capital=START
    trade=None
    trades=[]
    curve=[START]
    for bar in five:
        t,opening,high,low,closing,_volume=bar
        if not(start_ms<=t<end_ms):
            continue
        was_open=trade is not None
        if trade:
            d=trade['direction']; stop=trade['stop']; target=trade['target']
            stop_hit=low<=stop if d==1 else high>=stop
            target_hit=high>=target if d==1 else low<=target
            if stop_hit or target_hit or t>=trade['deadline']:
                if stop_hit:
                    exit_raw=min(opening,stop) if d==1 else max(opening,stop)
                    reason='stop'
                elif target_hit:
                    exit_raw=target
                    reason='target'
                else:
                    exit_raw=opening
                    reason='timeout'
                exit_fill=exit_raw*(1-d*SLIP)
                pnl=(exit_fill-trade['entry'])*d*trade['qty'] - FEE*(trade['entry']+exit_fill)*trade['qty']
                capital+=pnl
                curve.append(capital)
                trades.append({'pnl':pnl,'open':trade['open_time'],'close':t,'result':reason})
                trade=None
        if was_open:
            continue   # No future-looking same-bar re-entry.
        ev=events.get(t)
        if ev is None or capital<=0:
            continue
        d=ev['direction']
        entry=opening*(1+d*SLIP)
        risk=(entry-ev['stop'])*d
        if risk<=0:
            continue
        qty=min(capital*FRACTION_RISK/risk,capital*MAX_NOTIONAL/entry)
        if qty<=0:
            continue
        trade={'direction':d,'qty':qty,'entry':entry,
               'stop':ev['stop'],'target':ev['target'],
               'deadline':t+ev['timeout'],'open_time':t}
        stop_hit=low<=ev['stop'] if d==1 else high>=ev['stop']
        target_hit=high>=ev['target'] if d==1 else low<=ev['target']
        if stop_hit or target_hit:
            exit_raw=(min(opening,ev['stop']) if d==1 else max(opening,ev['stop'])) if stop_hit else ev['target']
            fill=exit_raw*(1-d*SLIP)
            pnl=(fill-entry)*d*qty - FEE*(entry+fill)*qty
            capital+=pnl;curve.append(capital)
            trades.append({'pnl':pnl,'open':t,'close':t,'result':'stop' if stop_hit else 'target'})
            trade=None
    if trade:
        endbar=next((b for b in reversed(five) if start_ms<=b[0]<end_ms),None)
        if endbar is not None:
            d=trade['direction']
            fill=endbar[4]*(1-d*SLIP)
            pnl=(fill-trade['entry'])*d*trade['qty'] - FEE*(trade['entry']+fill)*trade['qty']
            capital+=pnl;curve.append(capital)
            trades.append({'pnl':pnl,'open':trade['open_time'],'close':endbar[0],'result':'end'})
    return summarize(trades,start_ms,end_ms,curve)

def main():
    end=int(time.time()*1000)
    end-=end%MS['4H']
    start=end-DAYS*86_400_000
    develop=start+(WARMUP_DAYS*86_400_000)
    holdout=develop+(TRAIN_DAYS*86_400_000)
    holdout-=holdout%MS['4H']
    windows={'development':(develop,holdout),'validation':(holdout,end)}
    report={
        'complete':False,'asof_utc':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
        'interval_utc':{'start':dt.datetime.fromtimestamp(start/1000,dt.timezone.utc).isoformat(),
                        'development_from':dt.datetime.fromtimestamp(develop/1000,dt.timezone.utc).isoformat(),
                        'validation_from':dt.datetime.fromtimestamp(holdout/1000,dt.timezone.utc).isoformat()},
        'data_source':'Bitget USDT futures, v2 historical candles BTCUSDT / ETHUSDT (not spot)',
        'assumptions':{'taker_fee_per_side':FEE,'slippage_per_side':SLIP,
                       'risk_budget_frac':FRACTION_RISK,'max_notional_x':MAX_NOTIONAL,
                       'same_bar_stop_first':True,'funding_modeled':False,
                       'selection':'seven predeclared strategies; report all'},
        'methods':list(METHODS),'data_checks':{},'results':{},'errors':[]
    }
    for symbol in SYMBOLS:
        try:
            data={}
            for tf in ('5m','15m','1H','4H'):
                rows,calls=bt.history(symbol,tf,start,end)
                data[tf]=rows
                report['data_checks'][symbol+':'+tf]={'bars':len(rows),'pages':calls,
                                  'first':rows[0][0],'last':rows[-1][0]}
            feat={tf:features(data[tf]) for tf in ('15m','1H','4H')}
            h4feat=feat['4H']
            h4times=h4feat['time']
            candidates={name:{} for name in METHODS}
            frames={'15m':('M15_OVERSOLD_TREND',),
                    '1H':('H1_CHANNEL20','H1_CHANNEL55','H1_PULLBACK_EMA20','H1_BB_REVERSION'),
                    '4H':('H4_CHANNEL20','H4_EMA_TREND')}
            for tf, names in frames.items():
                rows=data[tf]
                features_tf=feat[tf]
                for i in range(220,len(rows)):
                    t=rows[i][0]+MS[tf]
                    if not develop<=t<end:
                        continue
                    j=hft=htf_index(h4times,t,MS['4H'])
                    if j<220:
                        continue
                    for method in names:
                        ev=make_signal(symbol,method,rows,i,features_tf,h4feat,j)
                        if ev:
                            candidates[method][t]=ev
            for method in METHODS:
                report['results'][symbol+':'+method]={}
                for name,(a,b) in windows.items():
                    vals=evaluate(data['5m'],candidates[method],a,b)
                    report['results'][symbol+':'+method][name]=vals
                print(symbol,method,report['results'][symbol+':'+method],flush=True)
        except Exception as exc:
            err=f'{symbol}: {type(exc).__name__}: {str(exc)[:300]}'
            report['errors'].append(err)
            print('ERROR',err,flush=True)
    report['complete']=len(report['results'])==len(METHODS)*len(SYMBOLS) and not report['errors']
    (ROOT/'research_alternatives_report.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FINAL',{k:report[k] for k in ('complete','errors','interval_utc')},flush=True)
    if not report['complete']:
        raise SystemExit(1)

if __name__=='__main__':
    main()
