# -*- coding: utf-8 -*-
"""Read-only, UTC closed-candle Bitget 4h EMA transition scan. No orders or secrets."""
import datetime as dt
import json
import math
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://api.bitget.com"
FOUR = 4 * 60 * 60 * 1000
MIN_BARS = 800
SYMBOLS = ("BTCUSDT", "ETHUSDT")


def get(path, **params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Public4hEmaScan/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        packet = json.load(response)
    if packet.get("code") != "00000" or not isinstance(packet.get("data"), list):
        raise RuntimeError("Bitget public API invalid: " + str(packet.get("msg")))
    return packet["data"]


def parse(raw, now):
    out = {}
    for item in raw:
        if len(item) < 5:
            raise ValueError("Bad candle format")
        ts = int(item[0])
        close = float(item[4])
        if ts % FOUR or not math.isfinite(close) or close <= 0:
            raise ValueError("Bad candle timestamp or price")
        if ts + FOUR <= now - 2000:
            out[ts] = close
    return out


def closed_history(symbol, now):
    recent = get("/api/v2/mix/market/candles", symbol=symbol,
                 productType="USDT-FUTURES", granularity="4H", limit="300")
    data = parse(recent, now)
    if not data:
        raise RuntimeError("No closed 4h candles")
    cursor = min(data)
    for _ in range(8):
        if len(data) >= MIN_BARS:
            break
        earlier = get("/api/v2/mix/market/history-candles", symbol=symbol,
                      productType="USDT-FUTURES", granularity="4H",
                      limit="200", endTime=str(cursor))
        page = parse(earlier, now)
        if not page:
            break
        older = {ts: px for ts, px in page.items() if ts < cursor}
        if not older:
            break
        data.update(older)
        cursor = min(older)
        time.sleep(.15)
    rows = sorted(data.items())
    if len(rows) < MIN_BARS:
        raise RuntimeError("Insufficient closed candles: " + str(len(rows)))
    if any(b[0] - a[0] != FOUR for a, b in zip(rows, rows[1:])):
        raise RuntimeError("Missing/duplicate 4h candle history")
    latest_expected = (now // FOUR) * FOUR - FOUR
    if rows[-1][0] != latest_expected:
        raise RuntimeError("Latest closed 4h candle unavailable")
    return rows


def ema(values, period):
    alpha = 2.0 / (period + 1)
    result = []
    v = values[0]
    for close in values:
        v += alpha * (close - v)
        result.append(v)
    return result


def alignment(e20, e50, e200):
    if e20 > e50 > e200:
        return "LONG"
    if e20 < e50 < e200:
        return "SHORT"
    return "KARISIK"


def utc(ms):
    return dt.datetime.fromtimestamp(ms/1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def scan(symbol, now):
    rows = closed_history(symbol, now)
    closes = [r[1] for r in rows]
    a, b, c = [ema(closes, period) for period in (20, 50, 200)]
    old = alignment(a[-2], b[-2], c[-2])
    new = alignment(a[-1], b[-1], c[-1])
    close_at = rows[-1][0] + FOUR
    events = []
    if symbol == "BTCUSDT":
        if b[-2] <= c[-2] and b[-1] > c[-1] and new == "LONG":
            events.append(("EMA50/200", "LONG"))
        if b[-2] >= c[-2] and b[-1] < c[-1] and new == "SHORT":
            events.append(("EMA50/200", "SHORT"))
    if old != new and new != "KARISIK":
        events.append(("EMA20/50/200" if symbol == "BTCUSDT" else "ETH 20/50/200 trend", new))
    result = {"symbol": symbol, "close_utc": utc(close_at),
              "last_closed_price": round(closes[-1], 4),
              "ema20": round(a[-1], 4), "ema50": round(b[-1], 4),
              "ema200": round(c[-1], 4),
              "previous_alignment": old, "current_alignment": new,
              "bars": len(rows), "events": events}
    return result


def main():
    now = int(time.time() * 1000)
    for sym in SYMBOLS:
        try:
            result = scan(sym, now)
            print("SCAN_JSON " + json.dumps(result, ensure_ascii=False), flush=True)
            # Signal freshness: do not notify for a transition from an old bar.
            close_ms = int(dt.datetime.strptime(
                result["close_utc"], "%Y-%m-%d %H:%M UTC"
            ).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
            if 0 <= now - close_ms <= 65 * 60_000:
                for method, direction in result["events"]:
                    print("NEW_CONFIRMED_SIGNAL " + json.dumps({
                        "symbol": sym, "strategy": method,
                        "close_utc": result["close_utc"], "direction": direction,
                        "risk": "Volatilite, EMA gecikmesi, yanlis kirilim, komisyon ve kayma. Kar garantisi yok."
                    }, ensure_ascii=False), flush=True)
        except Exception as exc:
            print("NO_VERIFIED_DATA " + sym + " " + type(exc).__name__ +
                  ": " + str(exc)[:140], flush=True)


if __name__ == "__main__":
    main()
