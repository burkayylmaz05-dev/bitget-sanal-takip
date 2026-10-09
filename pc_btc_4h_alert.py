# -*- coding: utf-8 -*-
"""BTC 4H pullback candidate: READ-ONLY signal alert, NEVER submit orders.

Research rule frozen from research_trend_v4.py, PULLBACK_BIDIR.
Latest 4H candle and daily trend must both be CLOSED (UTC).
Separate local dedup state; no historical alerts after offline periods.
"""
import datetime as dt
import math
import time
from pathlib import Path

import bitget_sinyal_takip as engine
import research_backtest as candles
import research_trend_v4 as study

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'pc_btc_4h_alert_state.json'
FOUR=study.FOUR
DAY=study.DAY
MAX_AGE_MS=90_000
MAX_TICK_AGE_MS=30_000


def last_closed_4h(now_ms, grace_ms=5000):
    return ((now_ms-grace_ms)//FOUR-1)*FOUR


class SignalAlert:
    def __init__(self,now_ms=None,state_file=STATE):
        if now_ms is None:
            now_ms=int(time.time()*1000)
        self.state_file=Path(state_file)
        self.state=engine.load_json(self.state_file,{})
        if not isinstance(self.state,dict):
            self.state={}
        self.state.setdefault('last_bar',last_closed_4h(now_ms))
        self.state.setdefault('last_alert',None)
        self.save()

    def save(self):
        engine.save_json(self.state_file,self.state)

    def check(self,now_ms,quote=None,quote_ms=None):
        """Return text to Telegram at most once per new closed 4H candle.

        Raise on data/API failure, so the caller can retry within 90 seconds.
        """
        latest=last_closed_4h(now_ms)
        if latest<=self.state['last_bar']:
            return None
        closed_at=latest+FOUR
        if now_ms-closed_at>MAX_AGE_MS:
            self.state['last_bar']=latest
            self.save()
            return None
        if quote is None or quote_ms is None or not (quote_ms<=now_ms and now_ms-quote_ms<=MAX_TICK_AGE_MS):
            raise RuntimeError('fresh BTC live quote unavailable')
        if not math.isfinite(quote) or quote<=0:
            raise RuntimeError('invalid BTC ticker')
        # Full 200-day daily EMA needs sufficient historical lead-in.
        start4=closed_at-165*DAY
        startd=(closed_at//DAY)*DAY-620*DAY
        endd=(closed_at//DAY)*DAY
        four,_calls=candles.history('BTCUSDT','4H',start4,closed_at)
        if four[-1][0]!=latest:
            raise RuntimeError('4H closed price not yet published')
        daily=study.daily_candles('BTCUSDT',startd,endd)
        if daily[-1][0]+DAY!=endd:
            raise RuntimeError('UTC daily candle not yet published')
        scenarios,_atr=study.event_map(four,daily)
        ev=scenarios['PULLBACK_BIDIR'].get(closed_at)
        self.state['last_bar']=latest
        self.save()
        if ev is None:
            return None
        if abs(quote-ev['ref'])>0.5*ev['atr']:
            return None
        d=ev['d']
        risk=(quote-ev['stop'])*d
        if risk<=0:
            return None
        direction='LONG' if d==1 else 'SHORT'
        entry=quote*(1+d*.0003)
        if (entry-ev['stop'])*d<=0:
            return None
        key=f'{direction}:{latest}'
        if self.state['last_alert']==key:
            return None
        self.state['last_alert']=key
        self.save()
        when=dt.datetime.fromtimestamp(closed_at/1000,dt.timezone.utc)
        return (
            f'BTC 4H EMA20 PULLBACK | {direction} ADAY (GERCEK EMIR YOK)\n'
            f'Kapanis UTC: {when:%Y-%m-%d %H:%M}\n'
            f'4H kapanis referansi: {ev["ref"]:,.2f} USDT\n'
            f'Canli fiyat: {quote:,.2f} USDT\n'
            f'Tahmini giris (+kayma): {entry:,.2f} USDT\n'
            f'Baslangic stop: {ev["stop"]:,.2f} USDT\n'
            f'Izleme: 2.5 x 4H ATR trailing stop, max 30 gun.\n'
            f'Risk modeli: nominal maksimum 1x; hedef stop riski %0.5.\n'
            'Tarihsel karlilik gelecekte garanti degil; '
            'funding ve gercek emir gerceklesmesi modele dahil degil.'
        )
