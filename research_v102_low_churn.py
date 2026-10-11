# -*- coding: utf-8 -*-
"""New predeclared low-turnover 4H BTC/ETH models vs fees; no trades.

Validate 2025H1,H2 then 2026H1,H2, all dated windows. Hypothetical
next-4H-open entry, stop first including entry bar, 1x notional cap,
fee 0.06% + slip 0.03% PER SIDE, stress 2x, no funding.
"""
import datetime as dt
import json
import research_backtest as api

DAY=86400000
FOUR=14400000
FEE=.0006
SLIP=.0003
CAP=1000.
MODELS=('EMA50_200_LONG','EMA50_200_BOTH','EMA100_200_LONG','DON20_10_LONG','DON55_20_LONG','DON20_10_BOTH')

def date(s):return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp()*1000)

def ema(x,n):
    a=2/(n+1);v=x[0];out=[]
    for x0 in x:v+=a*(x0-v);out.append(v)
    return out

def atr(bars,n=14):
    v=None;out=[]
    for i,(_,o,h,l,c,vol) in enumerate(bars):
        pre=bars[i-1][4] if i else o
        tr=max(h-l,abs(h-pre),abs(l-pre))
        v=tr if v is None else (v*(n-1)+tr)/n
        out.append(v)
    return out

def events(bars):
    c=[x[4] for x in bars]
    em50,em100,em200=[ema(c,n) for n in (50,100,200)]
    atrs=atr(bars)
    directions={m:[0]*len(bars) for m in MODELS}
    exit_channel={m:[False]*len(bars) for m in MODELS}
    for i in range(300,len(bars)):
        p=c[i];a=atrs[i]
        if not .001<a/p<.08:continue
        up=em50[i]>em200[i] and c[i]>em200[i] and em50[i]>em50[i-6]
        down=em50[i]<em200[i] and c[i]<em200[i] and em50[i]<em50[i-6]
        directions['EMA50_200_LONG'][i]=int(up)
        directions['EMA50_200_BOTH'][i]=1 if up else -1 if down else 0
        directions['EMA100_200_LONG'][i]=int(em100[i]>em200[i] and c[i]>em200[i] and em100[i]>em100[i-6])
        old20=bars[i-20:i];old55=bars[i-55:i]
        short_low=min(x[3] for x in bars[i-10:i])
        med_low=min(x[3] for x in bars[i-20:i])
        short_hi=max(x[2] for x in bars[i-10:i])
        high20=max(x[2] for x in old20);high55=max(x[2] for x in old55)
        low20=min(x[3] for x in old20)
        is20=p>high20 and p-high20<1.5*a
        is55=p>high55 and p-high55<1.5*a
        iss20=p<low20 and low20-p<1.5*a
        directions['DON20_10_LONG'][i]=1 if up and is20 else 0
        directions['DON55_20_LONG'][i]=1 if up and is55 else 0
        directions['DON20_10_BOTH'][i]=1 if up and is20 else (-1 if down and iss20 else 0)
        exit_channel['DON20_10_LONG'][i]=p<short_low
        exit_channel['DON55_20_LONG'][i]=p<med_low
        exit_channel['DON20_10_BOTH'][i]=p<short_low or p>short_hi
    return directions,exit_channel,atrs

def sim(bars,dirs,exits,atrs,method,start,end,fee=FEE,slip=SLIP):
    eq=CAP;pos=None;trades=[];peak=CAP;maxdd=0.;marked=eq
    ema_method=method.startswith('EMA')
    for i in range(301,len(bars)):
        t,o,h,l,c,vol=bars[i]
        if not start<=t<end:continue
        previous_dir=dirs[method][i-1]
        if pos:
            p=pos;d=p['d']
            stophit=l<=p['stop'] if d==1 else h>=p['stop']
            exitrule=(previous_dir!=d if ema_method else exits[method][i-1])
            if stophit or exitrule or t-p['opened']>=30*DAY:
                raw=(min(o,p['stop']) if d==1 else max(o,p['stop'])) if stophit else o
                fill=raw*(1-d*slip)
                pnl=(fill-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+fill)
                eq+=pnl
                trades.append((t,pnl))
                pos=None
            else:
                updated=c-d*(3.0 if ema_method else 2.5)*atrs[i]
                p['stop']=max(p['stop'],updated) if d==1 else min(p['stop'],updated)
        if pos is None and previous_dir!=0 and eq>0:
            prev_exited=bool(trades and trades[-1][0]==t)
            if not prev_exited:
                d=previous_dir
                entry=o*(1+d*slip)
                qty=min(eq/entry,eq*.005/(2.5*atrs[i-1]))
                if qty>0:
                    pos={'d':d,'qty':qty,'entry':entry,
                         'stop':entry-d*2.5*atrs[i-1],'opened':t}
                    if (l<=pos['stop'] if d==1 else h>=pos['stop']):
                        raw=min(o,pos['stop']) if d==1 else max(o,pos['stop'])
                        fill=raw*(1-d*slip)
                        pnl=(fill-entry)*d*qty-fee*qty*(entry+fill)
                        eq+=pnl;trades.append((t,pnl));pos=None
        if pos:
            p=pos;d=p['d'];fill=c*(1-d*slip)
            floating=(fill-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+fill)
            marked=eq+floating
        else:marked=eq
        peak=max(peak,marked);maxdd=min(maxdd,(marked/peak-1)*100)
    profit=sum(x for _,x in trades if x>0)
    loss=-sum(x for _,x in trades if x<=0)
    return {'net_pct':round((marked/CAP-1)*100,3),'closed':len(trades),
            'wins':sum(x>0 for _,x in trades),
            'pf':round(profit/loss,3) if loss else None,
            'dd_pct':round(maxdd,3),'open':pos is not None}

def main():
    start=date('2024-01-01');end=date('2026-10-11')
    parts=[('2025_H1','2025-01-01','2025-07-01'),
           ('2025_H2','2025-07-01','2026-01-01'),
           ('2026_H1','2026-01-01','2026-07-01'),
           ('2026_H2','2026-07-01','2026-10-11')]
    results={}
    for sym in ('BTCUSDT','ETHUSDT'):
        bars,_=api.history(sym,'4H',start,end)
        dirs,exits,atrs=events(bars)
        for method in MODELS:
            item={}
            for name,begin,finish in parts:
                normal=sim(bars,dirs,exits,atrs,method,date(begin),date(finish))
                stress=sim(bars,dirs,exits,atrs,method,date(begin),date(finish),fee=FEE*2,slip=SLIP*2)
                item[name]={'normal':normal,'double_cost_pct':stress['net_pct']}
            results[sym+':'+method]=item
            print('RESULT',sym,method,[(k,z['normal']['net_pct'],z['double_cost_pct'],
                                        z['normal']['closed']) for k,z in item.items()],flush=True)
    eligible=[(k,v) for k,v in results.items() if
              all(v[t]['normal']['net_pct']>0 and v[t]['double_cost_pct']>0
                  for t in ('2025_H1','2025_H2'))]
    eligible.sort(key=lambda kv:sum(kv[1][t]['double_cost_pct']
                  for t in ('2025_H1','2025_H2')),reverse=True)
    winner=eligible[0][0] if eligible else 'CASH'
    print('WINNER_FROM_2025',winner,flush=True)
    print('ALL_TREND_JSON',json.dumps({'winner':winner,'results':results,
        'funding_included':False,'fees_each_side':FEE,
        'slippage_each_side':SLIP},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
