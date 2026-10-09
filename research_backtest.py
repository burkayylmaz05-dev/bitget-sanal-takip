# -*- coding: utf-8 -*-
"""Reproducible no-order backtest for live BTC/ETH 5m,15m,1H,4H signal rules.

Historical Bitget USDT-FUTURES close candles, correct HTF as-of joins.
Entry at NEXT 5m open, conservative OHLC ambiguous fill (stop first, including entry bar),
standard taker fees and assumed slippage. Funding and real spread unavailable.
NO API KEYS, NO ORDERS. Writes only research_backtest_report.json.
"""
import bisect
import collections
import datetime as dt
import json
import math
import os
import random
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pc_zaman_dilimleri as rules

BASE = 'https://api.bitget.com/api/v2/mix/market/history-candles'
PERIOD = rules.TF_MS
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
FRAMES = rules.FRAMES
DAYS = int(os.environ.get('BACKTEST_DAYS', '120'))
# Historical training test partition (locked; no choosing "best" on test).
WARMUP_DAYS = 40
TAKER_FEE = 0.0006
SLIP_PER_SIDE = 0.0003
MAX_NOTIONAL_LEVERAGE = 1.0
RISK_BUDGET = 0.005
START_BALANCE = 1000.0
ROOT = Path(__file__).resolve().parent


def request(params):
    url = BASE + '?' + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    url, headers={'User-Agent': 'BTCETH-Research-NoOrders/1.0'}),
                    timeout=25) as response:
                packet = json.load(response)
            if packet.get('code') != '00000' or not isinstance(packet.get('data'), list):
                raise RuntimeError('Bitget: ' + str(packet.get('msg')))
            return packet['data']
        except Exception as exc:
            if attempt == 5:
                raise RuntimeError('Bitget history endpoint failure: ' +
                                   type(exc).__name__ + ': ' + str(exc)[:170]) from exc
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError('Unreachable')


def history(symbol, tf, start_ms, end_ms):
    period = PERIOD[tf]
    pointer = end_ms - end_ms % period
    raw = {}
    calls = 0
    while pointer >= start_ms:
        payload = request({
            'symbol': symbol, 'productType': 'USDT-FUTURES',
            'granularity': tf, 'endTime': str(pointer), 'limit': '200'
        })
        calls += 1
        valid = []
        for row in payload:
            try:
                bar = (int(row[0]), *(float(v) for v in row[1:6]))
            except (IndexError, ValueError, TypeError):
                continue
            if all(math.isfinite(x) for x in bar[1:]):
                valid.append(bar)
        if not valid:
            break
        for r in valid:
            if start_ms <= r[0] and r[0] + period <= end_ms:
                raw[r[0]] = r
        earliest = min(x[0] for x in valid)
        if earliest >= pointer:
            raise RuntimeError(f'Pagination stall {symbol} {tf}, timestamp={pointer}')
        # Bitget endTime is exclusive; using earliest-period skips a bar at each page seam.
        # Request up to earliest and de-duplicate the repeated boundary timestamp.
        pointer = earliest
        if calls > max(100, math.ceil((end_ms - start_ms) / period / 100)):
            raise RuntimeError('Pagination exceeded safety limit')
        if calls % 40 == 0:
            print(f'{symbol} {tf}: {calls} pages, {len(raw)} closed candles', flush=True)
        # below documented rate limit of 20/s IP; GitHub Actions runner only
        time.sleep(0.09)
    rows = [raw[k] for k in sorted(raw)]
    if not rows:
        raise RuntimeError(f'No historical rows {symbol} {tf}')
    missing = [(a[0], b[0]) for a, b in zip(rows, rows[1:]) if b[0] - a[0] != period]
    if missing:
        raise RuntimeError(f'Candle gaps: {symbol} {tf} first={missing[0]} count={len(missing)}')
    print(f'{symbol} {tf} OK: {len(rows)} candles / {calls} requests', flush=True)
    return rows, calls


def ema(values, period):
    a = 2 / (period + 1)
    result = []
    last = None
    for v in values:
        last = v if last is None else last + a * (v - last)
        result.append(last)
    return result


def indicator(rows):
    close = [r[4] for r in rows]
    e12, e26, e50, e200 = [ema(close, p) for p in (12, 26, 50, 200)]
    macd = [x - y for x, y in zip(e12, e26)]
    macds = ema(macd, 9)
    trends = [0 if i < 214 else
              1 if close[i] > e50[i] > e200[i] else
              -1 if close[i] < e50[i] < e200[i] else 0
              for i in range(len(rows))]
    rsi = [50.0] * len(rows)
    gains = losses = 0.0
    for i in range(1, len(rows)):
        delta = close[i] - close[i-1]
        if i <= 14:
            gains += max(delta, 0)
            losses += max(-delta, 0)
            if i == 14:
                gains /= 14
                losses /= 14
        else:
            gains = (gains * 13 + max(delta, 0)) / 14
            losses = (losses * 13 + max(-delta, 0)) / 14
            rsi[i] = (100.0 if gains and not losses else
                      50.0 if not gains and not losses else
                      100 - 100 / (1 + gains / losses))
    atr = [0.0] * len(rows)
    last_atr = 0.0
    for i in range(1, len(rows)):
        bar, prev = rows[i], rows[i-1]
        tr = max(bar[2]-bar[3], abs(bar[2]-prev[4]), abs(bar[3]-prev[4]))
        if i <= 14:
            last_atr += tr
            if i == 14:
                last_atr /= 14
        else:
            last_atr = (last_atr * 13 + tr) / 14
        if i >= 14:
            atr[i] = last_atr
    return dict(trends=trends, rsi=rsi, atr=atr,
                histogram=[a-b for a,b in zip(macd,macds)],
                closes=close)


def signal(rows, idx, frame, feature, directional):
    """Exact live-rule filters at idx, using indicators computed only to idx."""
    if idx < 214 or directional == 0:
        return None
    r = rows[idx]
    price = r[4]
    current_atr = feature['atr'][idx]
    if price <= 0 or current_atr <= 0:
        return None
    low_atr, high_atr = rules.ATR_BOUNDS[frame]
    if not low_atr <= current_atr / price <= high_atr:
        return None
    prior_volumes = [x[5] for x in rows[idx-21:idx-1]]
    vavg = sum(prior_volumes)/len(prior_volumes)
    ratio = r[5] / vavg if vavg else 0
    if ratio < 1.35:
        return None
    momentum = feature['rsi'][idx]
    if directional == 1 and not (53 <= momentum <= 73):
        return None
    if directional == -1 and not (27 <= momentum <= 47):
        return None
    histogram = feature['histogram'][idx]
    if (directional == 1 and histogram <= 0) or (directional == -1 and histogram >= 0):
        return None
    lookback = rows[idx-20:idx]
    high20, low20 = max(x[2] for x in lookback), min(x[3] for x in lookback)
    if (directional == 1 and price <= high20) or (directional == -1 and price >= low20):
        return None
    level = high20 if directional == 1 else low20
    if abs(price - level) > .8 * current_atr:
        return None
    if directional == 1:
        swing = min(x[3] for x in rows[idx-10:idx+1])
        stop = min(swing, price - 1.5 * current_atr)
        risk = price-stop
        target = price + 2.2*risk
    else:
        swing = max(x[2] for x in rows[idx-10:idx+1])
        stop = max(swing, price + 1.5 * current_atr)
        risk = stop-price
        target = price - 2.2*risk
    rmin, rmax = rules.RISK_BOUNDS[frame]
    if not rmin <= risk / price <= rmax:
        return None
    return {'signal_price': price, 'stop': stop, 'target': target, 'volratio': ratio,
            'rsi': momentum, 'bar': r[0], 'direction': directional}


def drawdown(equity_sequence):
    high = equity_sequence[0] if equity_sequence else START_BALANCE
    worst = 0
    for balance in equity_sequence:
        high = max(high,balance)
        worst = min(worst,balance/high-1)
    return worst


def simulate(sym, tf, five, signal_events, window_start, window_end):
    equity=START_BALANCE
    trade=None
    trades=[]
    equities=[START_BALANCE]
    signal_count=0
    for bar in five:
        now=bar[0]
        if now < window_start or now >= window_end:
            continue
        if trade:
            direction=trade['direction']
            stop, target=trade['stop'],trade['target']
            hit_stop = bar[3] <= stop if direction==1 else bar[2] >= stop
            hit_target = bar[2] >= target if direction==1 else bar[3] <= target
            exit_raw=None
            reason=None
            if hit_stop:  # Assume stop first if both prices reached in same 5m bar.
                exit_raw = min(stop,bar[1]) if direction==1 else max(stop,bar[1])
                reason='STOP'
            elif hit_target:
                exit_raw=target
                reason='TARGET'
            elif now >= trade['deadline']:
                exit_raw=bar[1]
                reason='TIME'
            if exit_raw is not None:
                exit_fill=exit_raw*(1-SLIP_PER_SIDE*direction)
                qty=trade['qty']
                gross=(exit_fill-trade['entry'])*direction*qty
                fees=TAKER_FEE*qty*(trade['entry']+exit_fill)
                pnl=gross-fees
                equity += pnl
                equities.append(equity)
                trades.append(dict(entry_utc=trade['time'], exit_utc=now, result=reason,
                                   direction='LONG' if direction==1 else 'SHORT',
                                   pnl=round(pnl,5), notional=round(qty*trade['entry'],2)))
                trade=None
        event=signal_events.get(now)
        if event is None:
            continue
        signal_count += 1
        if trade or equity<=0:
            continue
        direction=event['direction']
        price=bar[1]*(1+SLIP_PER_SIDE*direction)  # next 5m open + adverse slippage
        stop=event['stop']
        distance=(price-stop)*direction
        if distance<=0:
            continue
        qty=min(equity*RISK_BUDGET / distance, equity * MAX_NOTIONAL_LEVERAGE / price)
        if qty <=0:
            continue
        trade=dict(entry=price, qty=qty, stop=stop, target=event['target'],
                   direction=direction, time=now,
                   deadline=now + min(12*PERIOD[tf], 12*3600_000 if tf in ('5m','15m') else 48*3600_000))
        # Check newly-opened position within the SAME 5m entry candle.
        # Without this, immediate stop losses are missed and returns are too optimistic.
        hit_stop = (bar[3] <= stop) if direction==1 else (bar[2] >= stop)
        hit_target = (bar[2] >= trade['target']) if direction==1 else (bar[3] <= trade['target'])
        if hit_stop or hit_target:
            if hit_stop:  # Stop-first when OHLC path is ambiguous.
                raw_exit = (min(stop,bar[1]) if direction==1 else max(stop,bar[1]))
                reason='STOP'
            else:
                raw_exit=trade['target']
                reason='TARGET'
            exit_fill=raw_exit*(1-SLIP_PER_SIDE*direction)
            pnl=(exit_fill-trade['entry'])*direction*qty - TAKER_FEE*qty*(trade['entry']+exit_fill)
            equity+=pnl
            equities.append(equity)
            trades.append(dict(entry_utc=now,exit_utc=now,result=reason,
                               direction='LONG' if direction==1 else 'SHORT',
                               pnl=round(pnl,5),notional=round(qty*trade['entry'],2)))
            trade=None
    if trade:
        # Close at first available final bar opening, no position carried across samples.
        last = max((r for r in five if window_start <= r[0] < window_end), key=lambda x:x[0], default=None)
        if last:
            direction=trade['direction']
            exit_fill=last[4]*(1-SLIP_PER_SIDE*direction)
            pnl=(exit_fill-trade['entry'])*direction*trade['qty']-TAKER_FEE*trade['qty']*(trade['entry']+exit_fill)
            equity+=pnl
            equities.append(equity)
            trades.append(dict(entry_utc=trade['time'],exit_utc=last[0],result='END',direction='LONG' if direction==1 else 'SHORT',pnl=round(pnl,5),notional=round(trade['qty']*trade['entry'],2)))
    wins=[t['pnl'] for t in trades if t['pnl']>0]
    losses=[t['pnl'] for t in trades if t['pnl']<=0]
    profit_factor = round(sum(wins)/(-sum(losses)),3) if sum(losses)<0 else None
    return dict(symbol=sym, timeframe=tf, days=round((window_end-window_start)/86400000,1),
                signals=signal_count, closed_trades=len(trades),
                winners=len(wins), win_rate=round(len(wins)/len(trades)*100,2) if trades else None,
                net_usdt=round(equity-START_BALANCE,3),
                return_pct=round((equity/START_BALANCE-1)*100,3),
                max_drawdown_pct=round(drawdown(equities)*100,3),
                profit_factor=profit_factor, example_trades=trades[:3])


def main():
    now_ms=int(time.time()*1000)
    end_ms=now_ms-(now_ms%PERIOD['5m'])
    start_ms=end_ms - DAYS*86_400_000
    eval_start=start_ms+WARMUP_DAYS*86_400_000
    split_ms=eval_start+(end_ms-eval_start)*3//5
    split_ms -= split_ms%PERIOD['4H']
    result=dict(
        methodology='CLOSED signals; next 5m OPEN with 0.03% adverse slippage per side, 0.06% taker fee each side, stop first on ambiguous bars including entry bar, 1x maximum notional, 0.5% risk budget, funding/spread/latency not modeled.',
        data_source='Bitget USDT-FUTURES public historical candles (not Binance spot)',
        reproducible_code='research_backtest.py',
        asof_utc=dt.datetime.fromtimestamp(end_ms/1000,dt.timezone.utc).isoformat(),
        date_span=dict(start=dt.datetime.fromtimestamp(start_ms/1000,dt.timezone.utc).isoformat(),
                       warmup_end=dt.datetime.fromtimestamp(eval_start/1000,dt.timezone.utc).isoformat(),
                       split=dt.datetime.fromtimestamp(split_ms/1000,dt.timezone.utc).isoformat()),
        cost_assumptions={'fee_each_side':TAKER_FEE, 'slippage_each_side':SLIP_PER_SIDE,'funding_included':False},
        train=[], test=[], metadata={}, errors=[]
    )
    for symbol in SYMBOLS:
        try:
            data={}
            meta={}
            for frame in FRAMES:
                data[frame], reqs=history(symbol,frame,start_ms,end_ms)
                meta[frame]=dict(candles=len(data[frame]),calls=reqs,first=data[frame][0][0],last=data[frame][-1][0])
            result['metadata'][symbol]=meta
            # EMA 200 can only be used after enough observations.
            features={tf:indicator(data[tf]) for tf in FRAMES}
            ts={tf:[x[0] for x in data[tf]] for tf in FRAMES}
            events={tf:{} for tf in FRAMES}
            signal_totals=collections.Counter()
            for frame in FRAMES:
                for i in range(214,len(data[frame])):
                    r=data[frame][i]
                    decision_time=r[0]+PERIOD[frame]
                    if decision_time<eval_start or decision_time>=end_ms:
                        continue
                    direction=features[frame]['trends'][i]
                    if not direction:
                        continue
                    agree=True
                    for higher in FRAMES[FRAMES.index(frame)+1:]:
                        # latest higher candle fully closed at decision time.
                        j=bisect.bisect_right(ts[higher],decision_time-PERIOD[higher])-1
                        if j<214 or features[higher]['trends'][j]!=direction:
                            agree=False
                            break
                    if not agree:
                        continue
                    candidate=signal(data[frame],i,frame,features[frame],direction)
                    if candidate:
                        # next 5m candle timestamp == decision time
                        events[frame][decision_time]=candidate
                        signal_totals[frame]+=1
            print(symbol, 'signals:',dict(signal_totals),flush=True)
            for frame in FRAMES:
                for name,low,high in [('train',eval_start,split_ms),('test',split_ms,end_ms)]:
                    if low >= high:
                        raise ValueError('Invalid split')
                    one=simulate(symbol,frame,data['5m'],events[frame],low,high)
                    result[name].append(one)
        except Exception as exc:
            msg=f'{symbol}: {type(exc).__name__}: {str(exc)[:300]}'
            print('BACKTEST ERROR',msg,flush=True)
            result['errors'].append(msg)
    result['completed'] = len(result['train'])==8 and len(result['test'])==8 and not result['errors']
    ROOT.joinpath('research_backtest_report.json').write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REPORT:',json.dumps({k:result[k] for k in ('completed','train','test','errors')},ensure_ascii=False),flush=True)
    if not result['completed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
