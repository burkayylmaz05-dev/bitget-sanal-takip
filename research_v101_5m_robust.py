# -*- coding: utf-8 -*-
"""Research ONLY: Bitget BTC/ETH 5m 120-day chronological backtest, no orders.

First 60d development, next 60d validation. V10.1 5m Donchian55 plus
frozen higher-timeframe and volatility filters. At most 1x notional, 0.5%
stop risk budget. Next-bar entry, stop first incl entry bar, bars closed.
Fee=.06% and slippage=.03% EACH way; double cost stress, no funding.
"""
import bisect
import datetime as dt
import json
import time
import research_backtest as api

FIVE=300000
FOUR=14400000
DAY=86400000
FEE=.0006
SLIP=.0003
RISK=.005
START=1000.
CANDIDATES=('V101_D55','D55_HIGH_ATR','D55_4H_TREND','D55_4H_TREND_HIGH_ATR','D55_LONG_ONLY')

def ema(x,n):
    a=2/(n+1);value=x[0];out=[]
    for v in x:
        value+=a*(v-value);out.append(value)
    return out

def atr(bars,n=14):
    x=None;out=[]
    for i,(_,o,h,l,c,vol) in enumerate(bars):
        last=bars[i-1][4] if i else o
        tr=max(h-l,abs(h-last),abs(l-last))
        x=tr if x is None else (x*(n-1)+tr)/n
        out.append(x)
    return out

def signal_map(bars,four):
    closes=[v[4] for v in bars]
    e50,e200=ema(closes,50),ema(closes,200)
    a=atr(bars)
    fcloses=[v[4] for v in four]
    fe50,fe200=ema(fcloses,50),ema(fcloses,200)
    fends=[x[0]+FOUR for x in four]
    out={m:{} for m in CANDIDATES}
    for i in range(250,len(bars)):
        c=closes[i];t=bars[i][0]+FIVE
        if not .00045<a[i]/c<.055:continue
        up=e50[i]>e200[i] and e50[i]>e50[i-24] and c>e200[i]
        down=e50[i]<e200[i] and e50[i]<e50[i-24] and c<e200[i]
        old=bars[i-55:i]
        hi=max(x[2] for x in old)
        lo=min(x[3] for x in old)
        d=1 if up and c>hi and c-hi<1.5*a[i] else (-1 if down and c<lo and lo-c<1.5*a[i] else 0)
        if d==0:continue
        j=bisect.bisect_right(fends,t)-1
        htf_ok=(j>=210 and (fe50[j]>fe200[j] and fe50[j]>fe50[j-6] if d==1 else
                              fe50[j]<fe200[j] and fe50[j]<fe50[j-6]))
        ev={'d':d,'ref':c,'atr':a[i],'stop':c-d*2.7*a[i]}
        for name in CANDIDATES:
            if name in ('D55_HIGH_ATR','D55_4H_TREND_HIGH_ATR') and a[i]/c<.001:continue
            if name in ('D55_4H_TREND','D55_4H_TREND_HIGH_ATR') and not htf_ok:continue
            if name=='D55_LONG_ONLY' and d!=1:continue
            out[name][t]=ev
    return out,a

def replay(bars,events,atrs,start,end,fee=FEE,slip=SLIP):
    cash=START;pos=None;trades=[];peak=START;dd=0.;open_mark=None
    for i,bar in enumerate(bars):
        t,o,h,l,c,v=bar
        if not start<=t<end:continue
        was_open=pos is not None
        if not was_open and t in events and cash>0:
            ev=events[t];d=ev['d']
            if abs(o-ev['ref'])<=.5*ev['atr']:
                entry=o*(1+d*slip)
                dist=(entry-ev['stop'])*d
                if dist>0:
                    qty=min(cash*RISK/dist,cash/entry)
                    if qty>0:pos={'entry':entry,'qty':qty,'stop':ev['stop'],'d':d,'at':t,'deadline':t+72*3600000}
        if pos:
            p=pos;d=p['d']
            hit=l<=p['stop'] if d==1 else h>=p['stop']
            expired=t>=p['deadline']
            if hit or expired:
                raw=(min(o,p['stop']) if d==1 else max(o,p['stop'])) if hit else o
                exitfill=raw*(1-d*slip)
                pnl=(exitfill-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+exitfill)
                cash+=pnl
                trades.append({'ts':t,'d':d,'pnl':round(pnl,5),'reason':'STOP' if hit else 'TIME'})
                pos=None
            else:
                update=c-d*3.2*atrs[i]
                p['stop']=max(p['stop'],update) if d==1 else min(p['stop'],update)
        if pos:
            p=pos;d=p['d'];mark=c*(1-d*slip)
            unreal=(mark-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+mark)
            marked=cash+unreal;open_mark=unreal
        else:marked=cash;open_mark=None
        peak=max(peak,marked);dd=min(dd,(marked/peak-1)*100)
    positive=sum(x['pnl'] for x in trades if x['pnl']>0)
    negative=-sum(x['pnl'] for x in trades if x['pnl']<=0)
    net=cash+(open_mark or 0.)-START
    return {'net_pct':round(net/START*100,3),'realized_net':round(cash-START,3),
            'closed':len(trades),'wins':sum(x['pnl']>0 for x in trades),
            'profit_factor':round(positive/negative,3) if negative else None,
            'max_drawdown_pct':round(dd,3),
            'open_mark_pnl':round(open_mark,4) if open_mark is not None else None,
            'trades_last_5':trades[-5:]}

def main():
    now=(int(time.time()*1000)//FIVE)*FIVE
    devstart=now-120*DAY;holdout=now-60*DAY
    outputs={}
    for sym in ('BTCUSDT','ETHUSDT'):
        bars,pages=api.history(sym,'5m',devstart-5*DAY,now)
        four,_=api.history(sym,'4H',devstart-220*DAY,now)
        events,atrs=signal_map(bars,four)
        for method in CANDIDATES:
            dev=replay(bars,events[method],atrs,devstart,holdout)
            test=replay(bars,events[method],atrs,holdout,now)
            stress=replay(bars,events[method],atrs,holdout,now,fee=FEE*2,slip=SLIP*2)
            outputs[f'{sym}:{method}']={'development':dev,'holdout':test,'holdout_2x_cost':stress}
            print('RESULT',sym,method,'DEV',dev['net_pct'],'TEST',test['net_pct'],
                  'STRESS',stress['net_pct'],'N',test['closed'],flush=True)
    chosen=sorted(((k,v) for k,v in outputs.items() if v['development']['closed']>=20),
                  key=lambda x:x[1]['development']['net_pct'],reverse=True)
    winner=chosen[0][0] if chosen else None
    print('PRESELECTED_FROM_DEV_ONLY',winner,flush=True)
    print('COMPLETE_5M_RESEARCH_JSON',json.dumps({
        'end':dt.datetime.fromtimestamp(now/1000,dt.timezone.utc).isoformat(),
        'costs':{'fee':FEE,'slippage':SLIP,'funding_included':False},
        'selection':winner,'results':outputs},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
