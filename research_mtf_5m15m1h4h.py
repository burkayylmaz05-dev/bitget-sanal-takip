# -*- coding: utf-8 -*-
"""Frozen BTC ETH 5/15m entry + 1H/4H trend research. NO ORDERS.

Only closed 15m / 1H / 4H bars used at each 5m entry; 5m OHLC replay
conservatively enters at next 5m open, stop-first including entry candle.
Risk <=0.5% initial stop, notional <=1x, .06% fee + .03% slip each side.
Funding/real liquidity unavailable. Compare earlier/later 85 days separately.
"""
import bisect
import datetime as dt
import json
import time
import research_backtest as api

M5=300000;M15=900000;H1=3600000;H4=14400000;DAY=86400000
FEE=.0006;SLIP=.0003;INITIAL=1000.
METHODS=('D20_H1','D20_H4','D20_BOTH','D55_BOTH','EMA21_BOTH','PULLBACK_BOTH','H1BREAK_H4')

def ema(a,n):
    q=a[0];out=[];alpha=2/(n+1)
    for x in a:q+=alpha*(x-q);out.append(q)
    return out

def atr(a,n=14):
    val=None;out=[]
    for i,r in enumerate(a):
        pr=a[i-1][4] if i else r[1]
        tr=max(r[2]-r[3],abs(r[2]-pr),abs(r[3]-pr))
        val=tr if val is None else (val*(n-1)+tr)/n
        out.append(val)
    return out

def events(b15,b1,b4):
    c15=[x[4] for x in b15];c1=[x[4] for x in b1];c4=[x[4] for x in b4]
    e21,e55=[ema(c15,n) for n in (21,55)]
    a15=atr(b15);a1=atr(b1)
    e1_21,e1_50,e1_200=[ema(c1,n) for n in (21,50,200)]
    e4_50,e4_200=[ema(c4,n) for n in (50,200)]
    times1=[x[0]+H1 for x in b1];times4=[x[0]+H4 for x in b4]
    out={n:{} for n in METHODS}
    for i in range(260,len(b15)):
        t=b15[i][0]+M15
        j=bisect.bisect_right(times1,t)-1
        k=bisect.bisect_right(times4,t)-1
        if j<250 or k<250:continue
        c=c15[i];a=a15[i]
        if not .0007<a/c<.07:continue
        d1=1 if e1_50[j]>e1_200[j] and e1_50[j]>e1_50[j-6] and c1[j]>e1_200[j] else -1 if e1_50[j]<e1_200[j] and e1_50[j]<e1_50[j-6] and c1[j]<e1_200[j] else 0
        d4=1 if e4_50[k]>e4_200[k] and e4_50[k]>e4_50[k-6] and c4[k]>e4_200[k] else -1 if e4_50[k]<e4_200[k] and e4_50[k]<e4_50[k-6] and c4[k]<e4_200[k] else 0
        d15=1 if e21[i]>e55[i] and c>e55[i] else -1 if e21[i]<e55[i] and c<e55[i] else 0
        h20=max(x[2] for x in b15[i-20:i]);l20=min(x[3] for x in b15[i-20:i])
        h55=max(x[2] for x in b15[i-55:i]);l55=min(x[3] for x in b15[i-55:i])
        d20=1 if d15==1 and c>h20 and c-h20<1.2*a else -1 if d15==-1 and c<l20 and l20-c<1.2*a else 0
        d55=1 if d15==1 and c>h55 and c-h55<1.5*a else -1 if d15==-1 and c<l55 and l55-c<1.5*a else 0
        cr=1 if c15[i-1]<=e21[i-1] and c>e21[i] and d15==1 else -1 if c15[i-1]>=e21[i-1] and c<e21[i] and d15==-1 else 0
        pb=1 if d15==1 and b15[i-1][3]<=e21[i-1] and c>b15[i-1][2] else -1 if d15==-1 and b15[i-1][2]>=e21[i-1] and c<b15[i-1][3] else 0
        directions={'D20_H1':d20 if d20==d1 else 0,
            'D20_H4':d20 if d20==d4 else 0,
            'D20_BOTH':d20 if d20==d1==d4 else 0,
            'D55_BOTH':d55 if d55==d1==d4 else 0,
            'EMA21_BOTH':cr if cr==d1==d4 else 0,
            'PULLBACK_BOTH':pb if pb==d1==d4 else 0}
        for name,d in directions.items():
            if d:out[name][t]={'d':d,'reference':c,'atr':a,'stop':c-d*2.4*a,'trail':2.9,'max_hold':48*H1}
    for i in range(260,len(b1)):
        t=b1[i][0]+H1;k=bisect.bisect_right(times4,t)-1
        if k<250:continue
        c=c1[i];a=a1[i]
        if not .0012<a/c<.08:continue
        d4=1 if e4_50[k]>e4_200[k] and e4_50[k]>e4_50[k-6] and c4[k]>e4_200[k] else -1 if e4_50[k]<e4_200[k] and e4_50[k]<e4_50[k-6] and c4[k]<e4_200[k] else 0
        d1=1 if c>e1_50[i]>e1_200[i] else -1 if c<e1_50[i]<e1_200[i] else 0
        hi=max(x[2] for x in b1[i-20:i]);lo=min(x[3] for x in b1[i-20:i])
        br=1 if c>hi and c-hi<1.5*a else -1 if c<lo and lo-c<1.5*a else 0
        if br and br==d1==d4:
            out['H1BREAK_H4'][t]={'d':br,'reference':c,'atr':a,
                'stop':c-br*2*a,'trail':2.5,'max_hold':6*DAY}
    return out,a15,a1

def simulate(b5,b15,b1,maps,a15,a1,begin,end,fee=FEE,slip=SLIP):
    e15=[x[0]+M15 for x in b15];e1=[x[0]+H1 for x in b1]
    output={}
    for name,signals in maps.items():
        cash=INITIAL;pos=None;peak=INITIAL;dd=0.;trades=[];marked=cash
        for t,o,h,l,c,v in b5:
            if not begin<=t<end:continue
            ev=signals.get(t)
            if not pos and ev and cash>0 and abs(o-ev['reference'])<.35*ev['atr']:
                d=ev['d'];entry=o*(1+d*slip);risk=(entry-ev['stop'])*d
                if risk>0:
                    qty=min(cash*.005/risk,cash/entry)
                    if qty>0:pos=dict(d=d,entry=entry,qty=qty,stop=ev['stop'],
                                     trail=ev['trail'],expire=t+ev['max_hold'])
            if pos:
                d=pos['d'];hit=l<=pos['stop'] if d==1 else h>=pos['stop']
                expired=t>=pos['expire']
                if hit or expired:
                    raw=(min(o,pos['stop']) if d==1 else max(o,pos['stop'])) if hit else o
                    fill=raw*(1-d*slip)
                    net=(fill-pos['entry'])*d*pos['qty']-fee*pos['qty']*(pos['entry']+fill)
                    cash+=net;trades.append(net);pos=None
                else:
                    if name=='H1BREAK_H4' and t%H1==0:
                        j=bisect.bisect_right(e1,t)-1
                        if j>=0:
                            candidate=b1[j][4]-d*pos['trail']*a1[j]
                            pos['stop']=max(pos['stop'],candidate) if d==1 else min(pos['stop'],candidate)
                    elif name!='H1BREAK_H4' and t%M15==0:
                        j=bisect.bisect_right(e15,t)-1
                        if j>=0:
                            candidate=b15[j][4]-d*pos['trail']*a15[j]
                            pos['stop']=max(pos['stop'],candidate) if d==1 else min(pos['stop'],candidate)
            if pos:
                d=pos['d'];fill=c*(1-d*slip)
                marked=cash+(fill-pos['entry'])*d*pos['qty']-fee*pos['qty']*(pos['entry']+fill)
            else:marked=cash
            peak=max(peak,marked);dd=min(dd,(marked/peak-1)*100)
        plus=sum(v for v in trades if v>0);minus=-sum(v for v in trades if v<=0)
        output[name]={'net_pct':round((marked/INITIAL-1)*100,3),
            'closed':len(trades),'wins':sum(v>0 for v in trades),
            'pf':round(plus/minus,3) if minus else None,
            'dd_pct':round(dd,3),'open':bool(pos)}
    return output

def main():
    end=int(time.time()*1000)//M5*M5
    dev_start=end-170*DAY;val_start=end-85*DAY
    reports={}
    for sym in ('BTCUSDT','ETHUSDT'):
        b5,_=api.history(sym,'5m',dev_start-45*DAY,end)
        b15,_=api.history(sym,'15m',dev_start-45*DAY,end)
        b1,_=api.history(sym,'1H',dev_start-125*DAY,end)
        b4,_=api.history(sym,'4H',dev_start-205*DAY,end)
        print('FETCH',sym,'5m',len(b5),'15m',len(b15),'1h',len(b1),'4h',len(b4),flush=True)
        signals,a15,a1=events(b15,b1,b4)
        train=simulate(b5,b15,b1,signals,a15,a1,dev_start,val_start)
        test=simulate(b5,b15,b1,signals,a15,a1,val_start,end)
        stress=simulate(b5,b15,b1,signals,a15,a1,val_start,end,fee=FEE*2,slip=SLIP*2)
        for method in METHODS:
            key=sym+':'+method
            reports[key]={'train':train[method],'holdout':test[method],
                          'holdout_2x_cost':stress[method]}
            print('RESULT',key,'train',train[method]['net_pct'],'test',test[method]['net_pct'],
                '2x',stress[method]['net_pct'],'trades',test[method]['closed'],flush=True)
    candidates=sorted(((k,v) for k,v in reports.items() if v['train']['net_pct']>0 and v['train']['closed']>=8),
        key=lambda it:it[1]['train']['net_pct'],reverse=True)
    chosen=candidates[0][0] if candidates else None
    print('CHOSEN_FROM_FIRST_85_DAYS',chosen,flush=True)
    print('MTF_REPORT_JSON',json.dumps({'end_utc':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
        'chosen_by_development_only':chosen,'results':reports,'five_minute_execution':True,
        'entry_15min_and_1H_signals':True,'four_hour_filter':True,'fee_per_side':FEE,
        'slippage_per_side':SLIP,'funding_included':False,'real_order_execution':False},
        ensure_ascii=False),flush=True)

if __name__=='__main__':main()
