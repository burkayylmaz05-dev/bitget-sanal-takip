#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only, conservative Bitget USDT perpetual 5m/15m/1h/4h signal snapshot.
No keys, order API, trading, Telegram, or user notifications. Stdlib only.
Prints SIGNAL only if all confirmation gates pass. No guarantee of profit.
"""
import datetime as dt
import json
import math
import statistics
import time
import urllib.parse
import urllib.request

API = "https://api.bitget.com"
FRAMES = {"5m": 300000, "15m": 900000, "1H": 3600000, "4H": 14400000}
SYMBOLS = ("BTCUSDT", "ETHUSDT")

def get(path, params):
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "BitgetPublicSignalWatch/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        packet = json.load(r)
    if packet.get("code") != "00000":
        raise RuntimeError("Bitget market API: " + str(packet.get("msg")))
    return packet["data"]

def ema(values, length):
    out = [values[0]]
    k = 2/(length+1)
    for x in values[1:]:
        out.append(k*x+(1-k)*out[-1])
    return out

def rsi(values, period=14):
    gains = [max(values[i]-values[i-1], 0) for i in range(1,len(values))]
    losses = [max(values[i-1]-values[i], 0) for i in range(1,len(values))]
    up = sum(gains[:period])/period
    down = sum(losses[:period])/period
    for u,d in zip(gains[period:],losses[period:]):
        up=(up*(period-1)+u)/period
        down=(down*(period-1)+d)/period
    return 100 if down==0 else 100-100/(1+up/down)

def atr(rows, period=14):
    tr=[]
    for i,r in enumerate(rows):
        prev=rows[i-1][4] if i else r[1]
        tr.append(max(r[2]-r[3], abs(r[2]-prev), abs(r[3]-prev)))
    a=sum(tr[:period])/period
    for v in tr[period:]:
        a=(a*(period-1)+v)/period
    return a

def closed(symbol, frame, now):
    data=get("/api/v2/mix/market/candles", {
        "symbol":symbol, "productType":"USDT-FUTURES",
        "granularity":frame, "limit":"300"})
    rows=sorted((int(x[0]), *[float(y) for y in x[1:6]]) for x in data)
    ms=FRAMES[frame]
    rows=[r for r in rows if r[0]+ms <= now-3000]
    if len(rows)<225 or any(y[0]-x[0]!=ms for x,y in zip(rows,rows[1:])):
        raise RuntimeError(f"{symbol} {frame}: insufficient/gapped closed candles")
    if now-(rows[-1][0]+ms) > ms+90000:
        raise RuntimeError(f"{symbol} {frame}: stale last candle")
    return rows

def snapshot(rows):
    closes=[r[4] for r in rows]
    e20=ema(closes,20)
    e50=ema(closes,50)
    e200=ema(closes,200)
    macd=[a-b for a,b in zip(ema(closes,12),ema(closes,26))]
    hist=macd[-1]-ema(macd,9)[-1]
    c=closes[-1]
    if c>e20[-1]>e50[-1]>e200[-1] and e50[-1]>e50[-6]:
        direction="LONG"
    elif c<e20[-1]<e50[-1]<e200[-1] and e50[-1]<e50[-6]:
        direction="SHORT"
    else:
        direction="MIXED"
    volumes=[r[5] for r in rows[-21:-1]]
    vr=rows[-1][5]/statistics.mean(volumes) if statistics.mean(volumes)>0 else 0
    return {"trend":direction,"close":c,"ema20":e20[-1],
            "ema50":e50[-1],"ema200":e200[-1],
            "rsi":rsi(closes),"macd_hist":hist,
            "atr":atr(rows),"vol_ratio":vr,
            "bar_utc":dt.datetime.fromtimestamp((rows[-1][0]+(rows[-1][0]-rows[-2][0]))/1000,dt.timezone.utc).isoformat()}

def scan(symbol):
    now=int(time.time()*1000)
    raw=get("/api/v2/mix/market/ticker", {"symbol":symbol,"productType":"USDT-FUTURES"})
    raw=raw[0] if isinstance(raw,list) else raw
    price=float(raw["lastPr"])
    stamp=int(raw["ts"])
    if not math.isfinite(price) or price<=0 or abs(now-stamp)>90000:
        raise RuntimeError(symbol+": stale or invalid futures quote")
    rows={tf:closed(symbol,tf,now) for tf in FRAMES}
    data={tf:snapshot(rows[tf]) for tf in FRAMES}
    result={"symbol":symbol,"time_utc":dt.datetime.fromtimestamp(stamp/1000,dt.timezone.utc).isoformat(),
            "price":price,"frames":{tf:{"trend":x["trend"],"rsi":round(x["rsi"],1),
            "vol_ratio":round(x["vol_ratio"],2),"bar_utc":x["bar_utc"]} for tf,x in data.items()},
            "confirmed":False}
    trends=[data[tf]["trend"] for tf in FRAMES]
    if len(set(trends))!=1 or trends[0]=="MIXED":
        result["reason"]="Multi-timeframe EMA20/50/200 alignment absent"
        return result
    direction=trends[0]
    f5,f15,f1,f4=(data[t] for t in FRAMES)
    if f15["vol_ratio"]<1.5 or f5["vol_ratio"]<1.05 or f1["vol_ratio"]<0.7:
        result["reason"]="No convincing 15m/5m/1h volume confirmation"
        return result
    if not (55<=f15["rsi"]<=73 and 52<=f5["rsi"]<=78) if direction=="LONG" else not (27<=f15["rsi"]<=45 and 22<=f5["rsi"]<=48):
        result["reason"]="RSI momentum not confirmed"
        return result
    if (direction=="LONG" and (f15["macd_hist"]<=0 or f5["macd_hist"]<=0)) or (direction=="SHORT" and (f15["macd_hist"]>=0 or f5["macd_hist"]>=0)):
        result["reason"]="MACD momentum not confirmed"
        return result
    r15=rows["15m"]
    # A genuine 15-minute close beyond the previous 20 candles, not just an intrabar wick.
    level=max(x[2] for x in r15[-21:-1]) if direction=="LONG" else min(x[3] for x in r15[-21:-1])
    breakout=(r15[-1][4]>level if direction=="LONG" else r15[-1][4]<level)
    if not breakout:
        result["reason"]="No last closed 15m Donchian20 breakout"
        return result
    if abs(price-level)>0.8*f15["atr"] or (direction=="LONG" and price<level) or (direction=="SHORT" and price>level):
        result["reason"]="Current quote is too far from / has reversed the breakout"
        return result
    risk_distance=max(1.5*f15["atr"], .0015*price)
    if risk_distance/price > .02:
        result["reason"]="Stop distance too large"
        return result
    stop=price-risk_distance if direction=="LONG" else price+risk_distance
    target=price+2*risk_distance if direction=="LONG" else price-2*risk_distance
    result.update({"confirmed":True,"direction":direction,"breakout_level":round(level,4),
                   "entry_condition":"15m close confirmed, current price beyond breakout and <=0.8 ATR away",
                   "stop":round(stop,4),"target":round(target,4),
                   "volume_15m":round(f15["vol_ratio"],2),"reward_risk_gross":2.0,
                   "reason":"Four timeframes aligned; 15m breakout with volume and momentum"})
    return result

def main():
    for symbol in SYMBOLS:
        try:
            result=scan(symbol)
            print(("SIGNAL " if result["confirmed"] else "NO_SIGNAL ")+json.dumps(result,ensure_ascii=False),flush=True)
        except Exception as exc:
            print("DATA_UNAVAILABLE "+json.dumps({"symbol":symbol,"error":str(exc)[:200]}),flush=True)

if __name__=="__main__":
    main()
