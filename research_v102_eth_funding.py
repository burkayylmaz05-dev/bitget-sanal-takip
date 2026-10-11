# -*- coding: utf-8 -*-
"""ETH 4H EMA50/EMA200 88-day actual funding audit, historical only.

Use public Bitget ETHUSDT USDT futures 4H OHLC, real settlement rates.
Funding mark is approximated by 4H OPEN at settlement, exact rate/time.
Exact frozen research_v102_low_churn execution rules, 2x cost stress.
NO exchange private endpoints, no API credentials, no real orders.
"""
import datetime as dt
import json
import math
import time
import urllib.parse
import urllib.request
import research_backtest as api
import research_v102_low_churn as model

DAY=86400000
FOUR=14400000
EQUITY=1000.
FUNDING_URL='https://api.bitget.com/api/v3/market/history-fund-rate'

def rates(start,end):
    found={}
    oldest=end
    for cursor in range(1,101):
        url=FUNDING_URL+'?'+urllib.parse.urlencode({
            'category':'USDT-FUTURES','symbol':'ETHUSDT',
            'limit':'100','cursor':str(cursor)})
        for attempt in range(4):
            try:
                request=urllib.request.Request(url,headers={
                    'User-Agent':'ETH-ResearchFundingReadOnly/1.0'})
                with urllib.request.urlopen(request,timeout=25) as h:
                    pkt=json.load(h)
                if pkt.get('code')!='00000':
                    raise RuntimeError(str(pkt.get('msg')))
                break
            except Exception:
                if attempt>=3:raise
                time.sleep(1+attempt)
        batch=pkt['data']['resultList']
        if not batch:break
        for x in batch:
            t=int(x['fundingRateTimestamp'])
            if start<=t<end:
                found[t]=float(x['fundingRate'])
        oldest=min(int(x['fundingRateTimestamp']) for x in batch)
        if oldest<=start:break
        time.sleep(.15)
    if oldest>start:
        raise RuntimeError('Exchange funding history does not span entire audit')
    arr=sorted(found.items())
    if (not arr or arr[0][0]-start>16*3600000
        or end-arr[-1][0]>16*3600000
        or any(b[0]-a[0]>16*3600000 for a,b in zip(arr,arr[1:]))):
        raise RuntimeError('Incomplete Bitget funding series')
    return found

def replay(bars,dirs,exits,atrs,method,start,end,fund,fee=.0006,slip=.0003):
    eq=EQUITY;pos=None;peak=EQUITY;maxdd=0.;marked=eq
    count=0;fund_total=0.;fund_paid=0;gross_wins=0
    for i in range(301,len(bars)):
        t,o,h,l,c,vol=bars[i]
        if not start<=t<end:continue
        previous_dir=dirs[method][i-1]
        if pos:
            p=pos;d=p['d']
            if t in fund and p['opened']<t:
                amount=-d*fund[t]*p['qty']*o
                eq+=amount;fund_total+=amount;fund_paid+=1
            stophit=(l<=p['stop'] if d==1 else h>=p['stop'])
            exitrule=previous_dir!=d
            if stophit or exitrule or t-p['opened']>=30*DAY:
                raw=(min(o,p['stop']) if d==1 else max(o,p['stop'])) if stophit else o
                fill=raw*(1-d*slip)
                pnl=(fill-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+fill)
                eq+=pnl
                count+=1;gross_wins+=int(pnl>0)
                pos=None
            else:
                update=c-d*3.0*atrs[i]
                p['stop']=max(p['stop'],update) if d==1 else min(p['stop'],update)
        if pos is None and previous_dir!=0 and eq>0:
            # Track a close on this bar exactly as original model.
            exited=(locals().get('just_exited_at')==t)
            # Instead of relying on historical variable, set
            # just_exited_at whenever an old position closes below.
            if not exited:
                d=previous_dir;entry=o*(1+d*slip)
                qty=min(eq/entry,eq*.005/(2.5*atrs[i-1]))
                if qty>0:
                    pos={'d':d,'qty':qty,'entry':entry,
                         'stop':entry-d*2.5*atrs[i-1],'opened':t}
                    if (l<=pos['stop'] if d==1 else h>=pos['stop']):
                        raw=min(o,pos['stop']) if d==1 else max(o,pos['stop'])
                        fill=raw*(1-d*slip)
                        pnl=(fill-entry)*d*qty-fee*qty*(entry+fill)
                        eq+=pnl;count+=1;gross_wins+=int(pnl>0);pos=None
        if pos:
            p=pos;d=p['d'];fill=c*(1-d*slip)
            floating=(fill-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+fill)
            marked=eq+floating
        else:marked=eq
        peak=max(peak,marked);maxdd=min(maxdd,(marked/peak-1)*100)
    return {'net_pct':round((marked/EQUITY-1)*100,3),
            'funding_usdt':round(fund_total,4),
            'settlements':fund_paid,
            'trades':count,'gross_winning_trades':gross_wins,
            'max_dd_pct':round(maxdd,3)}

def main():
    end=int(time.time()*1000)//DAY*DAY
    start=end-88*DAY
    begin=start-240*DAY
    bars,_=api.history('ETHUSDT','4H',begin,end)
    dirs,exits,atrs=model.events(bars)
    x=rates(start,end)
    no_funding=model.sim(bars,dirs,exits,atrs,'EMA50_200_BOTH',start,end)
    audited=replay(bars,dirs,exits,atrs,'EMA50_200_BOTH',start,end,x)
    double=replay(bars,dirs,exits,atrs,'EMA50_200_BOTH',start,end,x,
                  fee=.0012,slip=.0006)
    # Cross-check independent funding engine with original EXACT baseline.
    zero=replay(bars,dirs,exits,atrs,'EMA50_200_BOTH',start,end,{})
    if abs(no_funding['net_pct']-zero['net_pct'])>.001 or no_funding['closed']!=zero['trades']:
        raise AssertionError(f'Funding replay baseline mismatch original={no_funding} check={zero}')
    print('FUNDING_AUDIT_JSON',json.dumps({
        'start':dt.datetime.fromtimestamp(start/1000,dt.timezone.utc).isoformat(),
        'end':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
        'rates_observed':len(x),'without_funding':no_funding,
        'with_actual_eth_funding':audited,'with_actual_funding_double_cost':double,
        'funding_mark':'approximate ETH 4H open',
        'notes':'backtest only; not forward execution; no true mark/impact'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
