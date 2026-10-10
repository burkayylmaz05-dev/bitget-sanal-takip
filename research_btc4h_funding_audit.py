# -*- coding: utf-8 -*-
"""Audit frozen BTC 4H EMA20 pullback, actual last-89d funding settlements.

Uses identical entry/exit/stop/trail model from research_trend_v4.py with
real Bitget V3 BTCUSDT settlement rates at actual timestamps, conservative
4H open as settlement mark proxy (mark price data unavailable).
No change to signal rules, no API keys, no real trades; public read-only.
"""
import datetime as dt
import json
import math
import time
import urllib.parse
import urllib.request

import research_backtest as core
import research_trend_v4 as trend

DAY=trend.DAY
FOUR=trend.FOUR
PERIOD=89
EQUITY=1000.
METHOD='PULLBACK_BIDIR'
URL='https://api.bitget.com/api/v3/market/history-fund-rate'


def get_funding(start,end):
    rates={}
    max_gap=0
    oldest=end
    for page in range(1,101):
        params=urllib.parse.urlencode({
            'category':'USDT-FUTURES','symbol':'BTCUSDT',
            'limit':'100','cursor':str(page)})
        req=urllib.request.Request(URL+'?'+params,
                headers={'User-Agent':'BTC4HAudit-PublicReadOnly/1.0'})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req,timeout=30) as resp:
                    payload=json.load(resp)
                if payload.get('code')!='00000':
                    raise RuntimeError(str(payload.get('msg')))
                break
            except Exception:
                if attempt==3:
                    raise
                time.sleep(1+attempt)
        batch=payload['data']['resultList']
        if not batch:
            break
        for item in batch:
            stamp=int(item['fundingRateTimestamp'])
            rate=float(item['fundingRate'])
            if start<=stamp<end and math.isfinite(rate):
                rates[stamp]=rate
        oldest=min(int(v['fundingRateTimestamp']) for v in batch)
        if oldest<=start:
            break
        time.sleep(.12)
    sortedrates=sorted(rates.items())
    if oldest>start:
        raise RuntimeError(f'Funding history cannot reach start; oldest={oldest}, start={start}')
    if not sortedrates or sortedrates[0][0]>start+16*3600_000 or sortedrates[-1][0]<end-16*3600_000:
        raise RuntimeError('Incomplete first/last funding interval')
    gaps=[b[0]-a[0] for a,b in zip(sortedrates,sortedrates[1:])]
    if gaps and max(gaps)>16*3600_000:
        raise RuntimeError(f'Funding missing >16 hours, max gap={max(gaps)/3600_000}')
    return sortedrates,page


def replay(four,events,atrs,rates,start,end,fee=.0006,slip=.0003):
    cash=EQUITY
    pos=None
    gross_funding=0.
    nfund=0
    closed=[]
    curve=[cash]
    peak=cash
    dd=0.
    bytimestamp={ts:r for ts,r in rates}
    for i,r in enumerate(four):
        t,o,h,l,c,v=r
        if not start<=t<end:
            continue
        was_open=pos is not None
        if was_open:
            p=pos
            # Exchange funding is at exact scheduled timestamp. Its exact
            # mark price is approximated by the next 4H OPEN.
            # Conservative convention: account funding at t even when
            # stop/timeout triggered in this same 4h candle.
            if t in bytimestamp and p['opened']<t:
                funding=-p['d']*bytimestamp[t]*p['qty']*o
                cash+=funding
                gross_funding+=funding
                nfund+=1
                p['funding']+=funding
            d=p['d']
            stop=l<=p['stop'] if d==1 else h>=p['stop']
            timeout=t>=p['deadline']
            if stop or timeout:
                raw=min(o,p['stop']) if d==1 else max(o,p['stop']) if stop else o
                # Correct precedence for long/short under stop (explicit)
                if stop:
                    raw=min(o,p['stop']) if d==1 else max(o,p['stop'])
                else:
                    raw=o
                x=raw*(1-d*slip)
                pnl=(x-p['entry'])*d*p['qty']-fee*p['qty']*(p['entry']+x)
                cash+=pnl
                closed.append({'opened_utc':dt.datetime.fromtimestamp(p['opened']/1000,dt.timezone.utc).strftime('%Y-%m-%d %H:%M'),
                               'closed_utc':dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).strftime('%Y-%m-%d %H:%M'),
                               'direction':'LONG' if d==1 else 'SHORT',
                               'trade_pnl_usdt':round(pnl,3),'funding_usdt':round(p['funding'],3),
                               'combined_usdt':round(pnl+p['funding'],3),
                               'cause':'STOP' if stop else 'TIME'})
                pos=None
            else:
                updated=c-d*p['trail']*atrs[i]
                p['stop']=max(p['stop'],updated) if d==1 else min(p['stop'],updated)
        if not was_open:
            sig=events.get(t)
            if sig and cash>0:
                d=sig['d']
                entry=o*(1+d*slip)
                risk=(entry-sig['stop'])*d
                if risk>0:
                    qty=min(cash*.005/risk,cash/entry)
                    if qty>0:
                        pos={'d':d,'entry':entry,'stop':sig['stop'],'qty':qty,
                             'trail':sig['trail_mult'],'opened':t,
                             'deadline':t+30*DAY,'funding':0.}
                        stop=l<=pos['stop'] if d==1 else h>=pos['stop']
                        if stop:
                            raw=min(o,pos['stop']) if d==1 else max(o,pos['stop'])
                            x=raw*(1-d*slip)
                            pnl=(x-entry)*d*qty-fee*qty*(entry+x)
                            cash+=pnl
                            closed.append({'opened_utc':str(t),
                                            'closed_utc':str(t),'direction':'LONG' if d==1 else 'SHORT',
                                            'trade_pnl_usdt':round(pnl,3),
                                            'funding_usdt':0,'combined_usdt':round(pnl,3),
                                            'cause':'ENTRY_BAR_STOP'})
                            pos=None
        if pos:
            p=pos
            x=c*(1-p['d']*slip)
            marked=cash+(x-p['entry'])*p['d']*p['qty']-fee*p['qty']*(p['entry']+x)
        else:
            marked=cash
        peak=max(peak,marked)
        dd=min(dd,100*(marked/peak-1))
        curve.append(marked)
    # Match research_trend_v4's forced mark-out at window end.
    if pos:
        last=next((x for x in reversed(four) if start<=x[0]<end),None)
        p=pos
        if last is not None:
            x=last[4]*(1-p['d']*slip)
            pnl=(x-p['entry'])*p['d']*p['qty']-fee*p['qty']*(p['entry']+x)
            cash+=pnl
            closed.append({'opened_utc':str(p['opened']),'closed_utc':str(last[0]),
                           'direction':'LONG' if p['d']==1 else 'SHORT',
                           'trade_pnl_usdt':round(pnl,3),
                           'funding_usdt':round(p['funding'],3),
                           'combined_usdt':round(pnl+p['funding'],3),
                           'cause':'WINDOW_END'})
    return {'closed':len(closed),'wins_including_funding':sum(t['combined_usdt']>0 for t in closed),
            'return_pct':round(100*(cash/EQUITY-1),3),
            'cash_usdt':round(cash,3),
            'total_funding_usdt':round(gross_funding,4),
            'funding_settlements_while_open':nfund,
            'max_marked_drawdown_pct':round(dd,3),
            'recent_trades':closed[-7:]}


def main():
    end=(int(time.time()*1000)//DAY)*DAY
    start=end-PERIOD*DAY
    lookback=end-620*DAY
    four,pages=core.history('BTCUSDT','4H',lookback,end)
    daily=trend.daily_candles('BTCUSDT',lookback,end)
    signals,atrs=trend.event_map(four,daily)
    fund,fp=get_funding(start,end)
    regular=replay(four,signals[METHOD],atrs,[],start,end)
    actual=replay(four,signals[METHOD],atrs,fund,start,end)
    stressed=replay(four,signals[METHOD],atrs,fund,start,end,fee=.0012,slip=.0006)
    legacy=trend.simulate(four,signals[METHOD],atrs,start,end)
    if abs(legacy['return_pct']-regular['return_pct'])>.02:
        raise AssertionError(f'Nonfunding model mismatch audit={regular["return_pct"]} original={legacy["return_pct"]}')
    print('AUDIT_REPORT_JSON',json.dumps({
        'period_start_utc':dt.datetime.fromtimestamp(start/1000,dt.timezone.utc).isoformat(),
        'period_end_utc':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
        'data':{'4h_bars':len(four),'daily_bars':len(daily),
                'funding_rates':len(fund),'funding_pages':fp,'4h_pages':pages},
        'without_funding':regular,'with_actual_funding':actual,
        'double_fees_slip_with_actual_funding':stressed,
        'note':'Funding Mark price approximated with 4h open, precise funding timestamp. Recent 89d only. Backtest not forward orders.',
    },ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
