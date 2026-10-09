# -*- coding: utf-8 -*-
"""PC icin BTC/ETH 5m,15m,1H,4H bagimsiz kapanmis-mum aday sinyalleri.

Esik degerleri deneysel filtrelerdir; test edilmis/garantili karlilik ifade etmez.
Yalnizca public piyasa verisi okur. Emir/islem API'si bulunmaz.
"""
import bitget_sinyal_takip as engine

FRAMES = ("5m", "15m", "1H", "4H")
TF_MS = {name: engine.TF_MS[name] for name in FRAMES}
# Farkli zaman dilimlerinde ATR ve stop mesafesi farkli olabilir.
ATR_BOUNDS = {
    "5m": (0.0010, 0.014),
    "15m": (0.0015, 0.024),
    "1H": (0.0020, 0.055),
    "4H": (0.0040, 0.100),
}
RISK_BOUNDS = {
    "5m": (0.0015, 0.018),
    "15m": (0.0020, 0.035),
    "1H": (0.0030, 0.070),
    "4H": (0.0050, 0.150),
}


def closed_bar(now_ms, timeframe="5m", delay_ms=5_000):
    """Tanimli mum kapanisindan en az delay_ms sonra son kapanan mumun acilis zamani."""
    period = TF_MS[timeframe]
    return ((now_ms - delay_ms) // period - 1) * period


def fetch_market(symbol):
    """Her sembol icin veriyi bir kez topla; ayni anda kapanan TF'lerde yeniden indirme."""
    return {tf: engine.candles(symbol, tf) for tf in FRAMES}


def analyze(symbol, timeframe, data):
    """Sinyal icin hedef TF ve ondan buyuk TF'ler ayni yone bakmalidir."""
    if timeframe not in FRAMES:
        raise ValueError("Desteklenmeyen zaman dilimi: " + str(timeframe))
    rows = data[timeframe]
    trends = {tf: engine.classify(data[tf]) for tf in FRAMES}
    direction = trends[timeframe]
    if direction == "KARISIK":
        return None, trends, "Ana mumda net trend yok"
    for higher in FRAMES[FRAMES.index(timeframe) + 1:]:
        if trends[higher] != direction:
            return None, trends, higher + " trend uyumsuz"

    closes = [r[4] for r in rows]
    price = closes[-1]
    current_atr = engine.atr(rows)
    if price <= 0 or current_atr <= 0:
        return None, trends, "ATR/fiyat gecersiz"
    atr_frac = current_atr / price
    low_atr, high_atr = ATR_BOUNDS[timeframe]
    if not low_atr <= atr_frac <= high_atr:
        return None, trends, "Volatilite filtresi"

    prior_volumes = [r[5] for r in rows[-22:-2]]
    mean_volume = sum(prior_volumes) / len(prior_volumes)
    volume_ratio = rows[-1][5] / mean_volume if mean_volume > 0 else 0
    if volume_ratio < 1.35:
        return None, trends, "Hacim yetersiz"

    momentum = engine.rsi(closes)
    if direction == "LONG" and not 53 <= momentum <= 73:
        return None, trends, "RSI filtresi"
    if direction == "SHORT" and not 27 <= momentum <= 47:
        return None, trends, "RSI filtresi"

    fast = engine.ema_series(closes, 12)
    slow = engine.ema_series(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    macd_signal = engine.ema_series(macd, 9)
    histogram = macd[-1] - macd_signal[-1]
    if (direction == "LONG" and histogram <= 0) or (direction == "SHORT" and histogram >= 0):
        return None, trends, "MACD filtresi"

    high20 = max(r[2] for r in rows[-21:-1])
    low20 = min(r[3] for r in rows[-21:-1])
    if direction == "LONG" and price <= high20:
        return None, trends, "Yukari kirilim yok"
    if direction == "SHORT" and price >= low20:
        return None, trends, "Asagi kirilim yok"

    level = high20 if direction == "LONG" else low20
    if abs(price - level) > 0.8 * current_atr:
        return None, trends, "Kirilmadan fazla uzak"
    if direction == "LONG":
        swing = min(r[3] for r in rows[-11:])
        stop = min(swing, price - 1.5 * current_atr)
        risk = price - stop
        target = price + 2.2 * risk
    else:
        swing = max(r[2] for r in rows[-11:])
        stop = max(swing, price + 1.5 * current_atr)
        risk = stop - price
        target = price - 2.2 * risk

    min_risk, max_risk = RISK_BOUNDS[timeframe]
    if not min_risk <= risk / price <= max_risk:
        return None, trends, "Stop mesafesi uygun degil"

    return {
        "symbol": symbol, "timeframe": timeframe, "direction": direction,
        "entry": price, "stop": stop, "target": target,
        "atr": current_atr, "rsi": momentum,
        "volume_ratio": volume_ratio, "candle": rows[-1][0]
    }, trends, "ADAY"
