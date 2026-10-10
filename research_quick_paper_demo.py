# -*- coding: utf-8 -*-
"""Historical demonstration of V8's EMA21 5m paper logic, never live orders.

All bars are historical Bitget BTC/ETH USDT Futures CLOSED candles.
Next bar OPEN entry after signal close, pessimistic slip/fees, stop first if
both exit levels hit, 4h timeout. No funding, L2 liquidity or perfect fills.
This is explicitly a REPLAY, not real-time forward tracking, and is not proof
of profitability. No credentials, no state files used by the Windows bot.
"""
import datetime as dt
import json
import time

import research_backtest as data
import bitget_sinyal_takip as indicators

FIVE=300_000
DAYS=7
WARMUP=250
START=1000.0
FEE=.0006
SLIP=.0003
MAX_RISK=.005
MAX_LEVERAGE=1.0


def atr_series(rows):
    out=[0.0]*len(rows)
    if len(rows)<16:
        return out
    initial=[]
    for i in range(1,len(rows)):
        prev=rows[i-1][4]
        bar=rows[i]
        tr=max(bar[2]-bar[3],abs(bar[2]-prev),abs(bar[3]-prev))
        if i <= 14:
            initial.append(tr)
            if i==14:
                out[i]=sum(initial)/14
        else:
            out[i]=(out[i-1]*13+tr)/14
    return out


def stamp(ms):
    return dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).strftime('%m-%d %H:%M UTC')


def replay(symbol, rows, first_ms):
    closes=[r[4] for r in rows]
    ema=indicators.ema_series(closes,21)
    atr=atr_series(rows)
    equity=START
    peak=START
    dd=0.
    trades=[]
    open_trade=None
    for idx in range(WARMUP,len(rows)-1):
        current=rows[idx]
        nxt=rows[idx+1]
        # Only data from CLOSED bars; entry at next bar's OPEN.
        if current[0]+FIVE<first_ms:
            continue
        # Process previous open position with current bar OHLC.
        if open_trade is not None:
            tr=open_trade
            d=tr['direction']
            if (current[0]-tr['opened']>=48*FIVE):
                fill=current[1]  # timeout at candle open
                reason='TIME'
            elif (current[3]<=tr['stop'] if d==1 else current[2]>=tr['stop']):
                fill=min(current[1],tr['stop']) if d==1 else max(current[1],tr['stop'])
                reason='STOP'
            elif (current[2]>=tr['target'] if d==1 else current[3]<=tr['target']):
                fill=tr['target']
                reason='TARGET'
            else:
                fill=None
                reason=None
            if fill is not None:
                exit_fill=fill*(1-d*SLIP)
                qty=tr['qty']
                fees=FEE*qty*(tr['entry']+exit_fill)
                net=(exit_fill-tr['entry'])*d*qty-fees
                equity+=net
                peak=max(peak,equity)
                dd=min(dd,100*(equity/peak-1))
                trades.append({
                    'open':stamp(tr['opened']),'close':stamp(current[0]),
                    'direction':'LONG' if d==1 else 'SHORT',
                    'entry':round(tr['entry'],2),'exit':round(exit_fill,2),
                    'reason':reason,'fee':round(fees,3),
                    'net_usdt':round(net,3)
                })
                open_trade=None

        if open_trade is not None:
            continue

        previous=closes[idx-1]-ema[idx-1]
        current_gap=closes[idx]-ema[idx]
        direction=1 if previous<=0 and current_gap>0 else -1 if previous>=0 and current_gap<0 else 0
        if direction==0 or atr[idx]<=0:
            continue
        # Advance only after signal candle closes. V8 uses fresh live quote,
        # replay uses the ACTUAL next-bar open to avoid any look-ahead.
        price=nxt[1]
        if price<=0 or abs(price-closes[idx])>.75*atr[idx]:
            continue
        entry=price*(1+direction*SLIP)
        stop_distance=max(1.5*atr[idx],price*.0025)
        stop=price-direction*stop_distance
        target=price+direction*2*stop_distance
        risk=(entry-stop)*direction
        reward=(target-entry)*direction
        if risk<=0 or reward<=0 or equity<=0:
            continue
        qty=min(equity*MAX_RISK/risk,equity*MAX_LEVERAGE/entry)
        if qty<=0:
            continue
        open_trade=dict(direction=direction,entry=entry,stop=stop,target=target,
                        qty=qty,opened=nxt[0])
        # Entry bar evaluated in the NEXT iteration, with conservative
        # stop-first exit to remove lookahead on intrabar price paths.

    # Do not invent PnL for the last still-open trade.
    return {
        'symbol':symbol,'period_days':DAYS,
        'first_candle_utc':stamp(first_ms),
        'last_candle_utc':stamp(rows[-1][0]),
        'opening_balance':START,
        'closing_balance_excluding_open':round(equity,3),
        'realized_net_usdt':round(equity-START,3),
        'realized_net_pct':round((equity/START-1)*100,3),
        'max_realized_drawdown_pct':round(dd,3),
        'closed':len(trades),
        'won':sum(t['net_usdt']>0 for t in trades),
        'lost':sum(t['net_usdt']<=0 for t in trades),
        'open_unrealized_not_counted':bool(open_trade),
        'recent_trades':trades[-12:],
    }


def main():
    now=int(time.time()*1000)
    end=(now//FIVE)*FIVE
    start=end-DAYS*24*60//5*FIVE
    for sym in ('BTCUSDT','ETHUSDT'):
        rows,calls=data.history(sym,'5m',start-(WARMUP+70)*FIVE,end)
        report=replay(sym,rows,start)
        report['api_requests']=calls
        print('PAPER_REPLAY_JSON '+json.dumps(report,ensure_ascii=False),flush=True)
    print('END_REPLAY - Historical replay only. Never live exchange orders.',flush=True)


if __name__=='__main__':
    main()
