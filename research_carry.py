# -*- coding: utf-8 -*-
"""Bitget spot-long + perp-short fully collateralized funding carry research.

All data sourced from Bitget public historical 1h futures + spot candles and
actual funding settlement history. Simulated, NEVER send trade orders.
This is NOT arbitrage guaranteed profit: basis changes, funding reversals,
futures collateral and liquidation, slippage, and execution risk remain.
"""
import bisect
import datetime as dt
import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DAYS=int(os.getenv('CARRY_DAYS','240'))
HOUR=3_600_000
DAY=86_400_000
SYMBOLS=('BTCUSDT','ETHUSDT')
START=1000.0
SPOT_FEE=0.001
PERP_FEE=0.0006
SLIP=0.0003
METHODS=('ALWAYS_CARRY','FUNDING_7D','FUNDING_14D')

def fetch(url,params):
    target=url+'?'+urllib.parse.urlencode(params)
    for i in range(5):
        try:
            r=urllib.request.Request(target,headers={'User-Agent':'CarryResearchPublicReadOnly/1.0'})
            with urllib.request.urlopen(r,timeout=30) as response:
                data=json.load(response)
            if data.get('code')!='00000':
                raise RuntimeError('Bitget code '+str(data.get('code'))+' '+str(data.get('msg')))
            return data['data']
        except Exception as exc:
            if i==4:
                raise
            time.sleep(min(2**i,9))

def get_candles(symbol,kind,start,end):
    if kind=='SPOT':
        url='https://api.bitget.com/api/v2/spot/market/history-candles'
        fixed={'symbol':symbol,'granularity':'1h','limit':'200'}
    else:
        url='https://api.bitget.com/api/v2/mix/market/history-candles'
        fixed={'symbol':symbol,'productType':'USDT-FUTURES','granularity':'1H','limit':'200'}
    pointer=end
    bars={}
    calls=0
    while pointer>=start:
        raw=fetch(url,{**fixed,'endTime':str(pointer)})
        calls+=1
        valid=[]
        for x in raw:
            try:
                row=(int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]))
            except (IndexError,TypeError,ValueError):
                continue
            if all(math.isfinite(v) and v>0 for v in row[1:]):
                valid.append(row)
        if not valid:
            break
        for r in valid:
            if start<=r[0] and r[0]+HOUR<=end:
                bars[r[0]]=r
        earliest=min(x[0] for x in valid)
        if earliest>=pointer:
            raise ValueError(f'{symbol} {kind}: API cursor stall')
        pointer=earliest
        if calls>120:
            raise RuntimeError(f'{symbol} {kind}: too many pages')
        time.sleep(.1)
    rows=[bars[x] for x in sorted(bars)]
    gaps=[(a[0],b[0]) for a,b in zip(rows,rows[1:]) if b[0]-a[0]!=HOUR]
    if gaps:
        raise RuntimeError(f'{symbol} {kind}: incomplete candles; {len(gaps)} missing periods, first {gaps[0]}')
    if len(rows)<DAYS*24-3:
        raise RuntimeError(f'{symbol} {kind}: insufficient history {len(rows)} for {DAYS} days')
    print(symbol,kind,'candles',len(rows),'pages',calls,flush=True)
    return rows,calls

def get_funding(symbol,start,end):
    url='https://api.bitget.com/api/v2/mix/market/history-fund-rate'
    rates={}
    pages=0
    while pages<100:
        raw=fetch(url,{'symbol':symbol,'productType':'USDT-FUTURES',
                       'pageSize':'100','pageNo':str(pages+1)})
        pages+=1
        if not raw:
            break
        for item in raw:
            try:
                stamp=int(item['fundingTime']);rate=float(item['fundingRate'])
            except (ValueError,TypeError,KeyError):
                continue
            if math.isfinite(rate) and start<=stamp<=end:
                rates[stamp]=rate
        earliest=min(int(item['fundingTime']) for item in raw)
        if earliest<start:
            break
        time.sleep(.1)
    records=sorted(rates.items())
    if not records or records[0][0]>start+2*DAY or records[-1][0]<end-2*DAY:
        raise RuntimeError(f'{symbol} funding insufficient coverage, {len(records)} records')
    max_gap=max([b[0]-a[0] for a,b in zip(records,records[1:])],default=0)
    if max_gap>DAY:
        raise RuntimeError(f'{symbol} funding missing intervals max gap {max_gap/HOUR:.1f} hours')
    print(symbol,'funding observations',len(records),'pages',pages,'rate range',
          round(min(x[1] for x in records),7),round(max(x[1] for x in records),7),flush=True)
    return records,pages

def condition(method,now,past):
    """Trading at hour open uses only historical funding settlements strictly BEFORE now."""
    if method=='ALWAYS_CARRY':
        return True,False
    days=7 if method=='FUNDING_7D' else 14
    window=[rate for timestamp,rate in past if now-days*DAY<=timestamp<now]
    if len(window)<days*2:
        return False,True
    avg=sum(window)/len(window)
    if method=='FUNDING_7D':
        return avg>=0.00007 and sum(r>0 for r in window)/len(window)>=0.7,avg<=0.00002
    return avg>=0.00010 and sum(r>0 for r in window)/len(window)>=0.7,avg<=0.000035

def simulate(spot,futures,rates,method,start,end):
    spot_by={r[0]:r for r in spot}
    fut_by={r[0]:r for r in futures}
    periods=sorted(set(spot_by).intersection(fut_by))
    capital=START
    position=None
    trades=[]
    equity_curve=[START]
    past=[]
    j=0
    cooldown=0
    funding_received=0.0
    fee_total=0.0
    basis_total=0.0
    min_futures_buffer=1.0
    settle_events=0
    regime_positive=0

    def close_pos(t,sp,fu,reason):
        nonlocal capital,position,fee_total,basis_total
        p=position
        spot_sell=sp*(1-SLIP)
        perp_cover=fu*(1+SLIP)
        qty=p['qty']
        gross_spot=(spot_sell-p['spot_buy'])*qty
        gross_perp=(p['perp_sell']-perp_cover)*qty
        cost=SPOT_FEE*(p['spot_buy']+spot_sell)*qty + PERP_FEE*(p['perp_sell']+perp_cover)*qty
        pnl=gross_spot+gross_perp+p['funding']-cost
        capital+=pnl
        fee_total+=cost
        basis_total+=gross_spot+gross_perp
        trades.append({'open':p['time'],'close':t,'reason':reason,'net':round(pnl,4),
                       'funding':round(p['funding'],4),'basis_pnl':round(gross_spot+gross_perp,4),
                       'fees':round(cost,4)})
        position=None

    for t in periods:
        if not start<=t<end:
            # history added before window for rate lookup later through direct loop.
            continue
        s=spot_by[t];f=fut_by[t]
        # The decision only sees rates settled BEFORE this hour; no look-ahead.
        already=[(time_,rate) for time_,rate in rates if t-14*DAY<=time_<t]
        enter,exit_=condition(method,t,already)
        # settle funding only for a position held since BEFORE that settlement.
        while j<len(rates) and rates[j][0]<=t:
            timestamp,rate=rates[j]
            if position and position['time']<timestamp:
                # 1H futures open near settlement (approximation of mark).
                payment=rate*position['qty']*f[1]
                position['funding']+=payment
                funding_received+=payment
                settle_events+=1
                regime_positive+=int(rate>0)
            j+=1
        if position:
            qty=position['qty']
            unreal=(s[4]*(1-SLIP)-position['spot_buy'])*qty+(position['perp_sell']-f[4]*(1+SLIP))*qty
            max_perp_draw=(f[2]-position['perp_sell'])*qty
            buffer=1-max_perp_draw/(position['perp_sell']*qty)
            min_futures_buffer=min(min_futures_buffer,buffer)
            # Emergency close if rising prices threaten isolated 1x collateral.
            liquidate=buffer<0.25
            held=t-position['time']
            max_hold=90*DAY
            min_hold=14*DAY if method!='ALWAYS_CARRY' else 0
            should_exit=liquidate or (held>=min_hold and exit_) or held>=max_hold
            if should_exit:
                close_pos(t,s[1],f[2] if liquidate else f[1],
                          'buffer_stop' if liquidate else 'signal_exit' if exit_ else 'max_hold')
                cooldown=t+3*DAY if method!='ALWAYS_CARRY' else t
        # Track estimated mark-to-market account equity (unrealized net of estimated exit costs)
        if position:
            p=position
            spot_mark=s[4]*(1-SLIP); perp_mark=f[4]*(1+SLIP)
            unreal=(spot_mark-p['spot_buy']+p['perp_sell']-perp_mark)*p['qty']
            totalcost=(SPOT_FEE*(p['spot_buy']+spot_mark)+PERP_FEE*(p['perp_sell']+perp_mark))*p['qty']
            equity_curve.append(capital+unreal+p['funding']-totalcost)
        else:
            equity_curve.append(capital)
        if not position and t>=cooldown and enter:
            # Spot fully paid, futures at <=1x isolated margin; no borrowing.
            s_entry=s[1]*(1+SLIP)
            f_entry=f[1]*(1-SLIP)
            qty=min(capital*.5/s_entry,capital*.5/f_entry)
            if qty>0:
                position={'qty':qty,'spot_buy':s_entry,'perp_sell':f_entry,
                          'time':t,'funding':0.0}
    if position:
        last=max(t for t in periods if start<=t<end)
        close_pos(last,spot_by[last][4],fut_by[last][4],'period_end')
        equity_curve.append(capital)
    peak=equity_curve[0]
    mdd=0
    for value in equity_curve:
        peak=max(peak,value)
        mdd=min(mdd,value/peak-1)
    gain=sum(t['net'] for t in trades)
    positive=sum(t['net']>0 for t in trades)
    return {'trades':len(trades),
            'winners':positive,
            'gain_pct':round((capital/START-1)*100,3),
            'net_usdt':round(capital-START,3),
            'max_drawdown_pct':round(mdd*100,3),
            'funding_collected_usdt':round(funding_received,3),
            'basis_pnl_usdt':round(basis_total,3),
            'trading_fees_usdt':round(fee_total,3),
            'settlements_while_held':settle_events,
            'positive_rate_share_held':round(regime_positive/settle_events,3) if settle_events else None,
            'worst_isolated_margin_buffer_frac':round(min_futures_buffer,3),
            'sample_trades':trades[:3]}

def main():
    now=int(time.time()*1000)
    end=now-now%HOUR
    start=end-DAYS*DAY
    develop=start+50*DAY
    validate=develop+100*DAY
    result={'complete':False,'asof':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
            'data_source':'Bitget public BTC ETH spot and USDT futures historical 1H, true funding timestamps',
            'periods':{'start':start,'development':develop,'validation':validate,'end':end},
            'assumptions':{'spot_taker_per_side':SPOT_FEE,'perp_taker_per_side':PERP_FEE,
                           'adverse_slippage_each_leg_each_side':SLIP,
                           'spot_weight':0.5,'perp_short_notional_to_initial_capital':0.5,
                           'funding_mark_proxy':'contemporaneous perp hourly open',
                           'collateral_liquidation_proxied':True,'no_borrowing':True,
                           'live_order_reality_tested':False},
            'sources':{},'results':{},'errors':[]}
    for symbol in SYMBOLS:
        try:
            spot,sp_pages=get_candles(symbol,'SPOT',start,end)
            fut,fu_pages=get_candles(symbol,'USDT-FUTURES',start,end)
            funding,fn_pages=get_funding(symbol,start,end)
            result['sources'][symbol]={'spot_1h':len(spot),'future_1h':len(fut),
                                       'funding_settlements':len(funding),
                                       'spot_pages':sp_pages,'perp_pages':fu_pages,'funding_pages':fn_pages,
                                       'funding_total_rate':round(sum(rate for _,rate in funding),4)}
            for method in METHODS:
                res={'development':simulate(spot,fut,funding,method,develop,validate),
                     'validation':simulate(spot,fut,funding,method,validate,end)}
                result['results'][symbol+':'+method]=res
                print(symbol,method,res,flush=True)
        except Exception as exc:
            msg=f'{symbol}: {type(exc).__name__}: {str(exc)[:200]}'
            print('CARRY ERROR',msg,flush=True)
            result['errors'].append(msg)
    result['complete']=len(result['results'])==6 and not result['errors']
    (ROOT/'research_carry_report.json').write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FINAL',result['complete'],result['errors'],flush=True)
    if not result['complete']:
        raise SystemExit(1)

if __name__=='__main__':
    main()
