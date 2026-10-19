# -*- coding: utf-8 -*-
"""One-click Bitget BTC/ETH paper trading dashboard (v9).

No exchange credentials, no order API calls. Public Bitget USDT perpetual
quotes and actually CLOSED 4H/1Dutc candles. Every paper fill is hypothetical.
Uses frozen 2026-researched BTC 4H Donchian20 and ETH 4H Donchian55 setups.
Fees, slippage and funding caveats are explicitly displayed. The research
results are archived backtests, NEVER passed off as forward/live trades.
"""
import csv
import datetime as dt
import http.server
import json
import math
import os
from pathlib import Path
import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

VERSION = "9.3"
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "v9_sanal_durum.json"
LOG_PATH = ROOT / "v9_sanal_islemler.csv"
TELEGRAM_PATH = ROOT / "pc_telegram_ayar.json"
API = "https://api.bitget.com"
FOUR = 4 * 60 * 60 * 1000
FIFTEEN = 15 * 60 * 1000
FAST_ID = "BTC15M"
QUICK_ID = "BTC_HIZLI"
QUICK_HOLD_MS = 5 * 60 * 1000
QUICK_REENTRY_MS = 15 * 60 * 1000
QUICK_DAILY_CAP = 8
TECH_DURATION_MS = 90_000
DAY = 24 * 60 * 60 * 1000
SYMBOLS = ("BTCUSDT", "ETHUSDT")
LOOKBACK = {"BTCUSDT": 20, "ETHUSDT": 55}
FEE = .0006
SLIP = .0003
SEED = 1000.0
RISK = .005
MAX_NOTIONAL = 1.0
FRESH_TICK_MS = 60_000
MAX_TICK_GAP_MS = 180_000
CLOCK_SKEW_MS = 15_000  # tolerate ordinary Bitget-vs-Windows clock drift
MAX_SIGNAL_DELAY_MS = 120_000
PORT = 8765

# Research archived October 2026: independent 2026 windows, historical only.
RESEARCH = {
    "BTCUSDT": {
        "strategy": "4H DONCHIAN20 + DAILY EMA100/200",
        "jan_may": 1.503, "jan_may_trades": 8,
        "jun_oct": 1.297, "jun_oct_trades": 6,
        "double_cost": 1.067,
        "caveat": "2025 ilk yarida -%1.125. Canli karlilik kanitlanmadi."
    },
    "ETHUSDT": {
        "strategy": "4H DONCHIAN55 + DAILY EMA100/200",
        "jan_may": 1.629, "jan_may_trades": 6,
        "jun_oct": .453, "jun_oct_trades": 3,
        "double_cost": .385,
        "caveat": "Yalnizca 3 son donem islemi. Cok az veri; deneysel."
    }
}


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()


def utc_ms():
    return int(time.time() * 1000)


def fresh_4h(now):
    return ((now - 5000) // FOUR - 1) * FOUR


def fresh_15m(now):
    return ((now - 5000) // FIFTEEN - 1) * FIFTEEN


def ema(values, length):
    a = 2.0 / (length + 1)
    result = []
    prev = float(values[0])
    for x in values:
        prev = prev + a * (float(x) - prev)
        result.append(prev)
    return result


def atr(rows, length=14):
    if len(rows) < length + 2:
        raise ValueError("ATR mumlari eksik")
    value = None
    for i, row in enumerate(rows):
        prevclose = rows[i - 1][4] if i else row[1]
        tr = max(row[2] - row[3], abs(row[2] - prevclose),
                 abs(row[3] - prevclose))
        value = tr if value is None else (value * (length - 1) + tr) / length
    return value


def get_json(path, params):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        API + path + ("?" + query if query else ""),
        headers={"User-Agent": "BTCETH-Sanal-V9-PublicReadOnly/1.0",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=18) as resp:
        packet = json.load(resp)
    if packet.get("code") != "00000":
        raise RuntimeError(str(packet.get("msg", packet.get("code"))))
    return packet


def ticker(symbol):
    packet = get_json("/api/v2/mix/market/ticker", {
        "symbol": symbol, "productType": "USDT-FUTURES"})
    data = packet["data"]
    if isinstance(data, list):
        data = data[0]
    price = float(data.get("lastPr", 0))
    stamp = int(data.get("ts") or packet.get("requestTime") or utc_ms())
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Gecersiz fiyat")
    if abs(utc_ms() - stamp) > FRESH_TICK_MS:
        raise RuntimeError("Bitget ticker verisi gecikmis")
    return price, stamp


def recent_closed_four(symbol, now):
    packet = get_json("/api/v2/mix/market/candles", {
        "symbol": symbol, "productType": "USDT-FUTURES",
        "granularity": "4H", "limit": "300"})
    rows = sorted(
        (int(x[0]), *[float(v) for v in x[1:6]])
        for x in packet["data"])
    rows = [r for r in rows if r[0] + FOUR <= now - 3000]
    if len(rows) < 100:
        raise RuntimeError("Yeterli 4H mum yok")
    if any(b[0] - a[0] != FOUR for a, b in zip(rows, rows[1:])):
        raise RuntimeError("4H veri boslugu")
    return rows


def recent_closed_fifteen(now):
    packet = get_json("/api/v2/mix/market/candles", {
        "symbol": "BTCUSDT", "productType": "USDT-FUTURES",
        "granularity": "15m", "limit": "300"})
    rows = sorted((int(x[0]), *[float(v) for v in x[1:6]])
                  for x in packet["data"])
    rows = [r for r in rows if r[0]+FIFTEEN <= now-3000]
    if len(rows)<285:
        raise RuntimeError("BTC 15m icin EMA200 mumlari eksik")
    if any(b[0]-a[0]!=FIFTEEN for a,b in zip(rows, rows[1:])):
        raise RuntimeError("BTC 15m eksik mum")
    return rows


def fast_signal_from_closed(rows):
    """15m Donchian55 + EMA50/200 as tested on Bitget, no future candles."""
    if len(rows)<285:
        raise RuntimeError("15m mum sayisi yetersiz")
    closes=[r[4] for r in rows]
    e50=ema(closes,50)
    e200=ema(closes,200)
    c=closes[-1]
    a=atr(rows)
    if not(.001<a/c<.055):
        return None, "15m ATR filtresi"
    up=e50[-1]>e200[-1] and e50[-1]>e50[-25] and c>e200[-1]
    down=e50[-1]<e200[-1] and e50[-1]<e50[-25] and c<e200[-1]
    hi=max(r[2] for r in rows[-56:-1])
    lo=min(r[3] for r in rows[-56:-1])
    d=1 if up and c>hi and c-hi<1.5*a else (
        -1 if down and c<lo and lo-c<1.5*a else 0)
    if not d:
        return None, "15m trend / kirilim sinyali yok"
    return {"direction":d,"reference":c,"atr":a,
            "stop":c-d*2.7*a,"trail_atr":3.2,
            "signal_at":rows[-1][0]+FIFTEEN}, "15m ADAY"


def daily_closed(symbol, now, limit_days=620):
    """Paged UTC daily history, enough for stable 200 EMA and slope."""
    end = (now // DAY) * DAY
    earliest = end - limit_days * DAY
    cursor = end
    unique = {}
    for page in range(7):
        packet = get_json("/api/v2/mix/market/history-candles", {
            "symbol": symbol, "productType": "USDT-FUTURES",
            "granularity": "1Dutc", "limit": "200", "endTime": str(cursor)})
        rows = sorted((int(x[0]), *[float(v) for v in x[1:6]])
                      for x in packet["data"])
        if not rows:
            break
        for r in rows:
            if earliest <= r[0] and r[0] + DAY <= end:
                unique[r[0]] = r
        new_cursor = rows[0][0]
        if new_cursor >= cursor:
            raise RuntimeError("Gunluk veri sayfalama hatasi")
        cursor = new_cursor
        if cursor <= earliest:
            break
        time.sleep(.10)
    result = [unique[k] for k in sorted(unique)]
    if len(result) < 550 or result[-1][0] + DAY != end:
        raise RuntimeError("Gunluk EMA 200 verisi tamamlanmadi")
    if any(b[0] - a[0] != DAY for a, b in zip(result, result[1:])):
        raise RuntimeError("Gunluk veri boslugu")
    return result


def signal_from_closed(symbol, bars, days):
    """Identical 2026-screened Donchian rules, no currently forming candles."""
    size = LOOKBACK[symbol]
    if len(bars) < size + 20 or len(days) < 235:
        raise RuntimeError("Gosterge verileri eksik")
    last = bars[-1]
    c = last[4]
    a = atr(bars)
    if not .001 < a / c < .08:
        return None, "4H ATR filtresi"
    prices = [x[4] for x in days]
    e100 = ema(prices, 100)
    e200 = ema(prices, 200)
    up = prices[-1] > e100[-1] > e200[-1] and e100[-1] > e100[-16]
    down = prices[-1] < e100[-1] < e200[-1] and e100[-1] < e100[-16]
    prev_high = max(x[2] for x in bars[-size - 1:-1])
    prev_low = min(x[3] for x in bars[-size - 1:-1])
    direction = (
        1 if up and c > prev_high and c - prev_high <= 1.5 * a
        else -1 if down and c < prev_low and prev_low - c <= 1.5 * a
        else 0)
    if not direction:
        return None, "Kirilim + gunluk trend uyusmuyor"
    return {
        "direction": direction,
        "reference": c,
        "atr": a,
        "stop": c - direction * 2.5 * a,
        "trail_atr": 3.0,
        "signal_bar": last[0],
        "signal_at": last[0] + FOUR
    }, "ADAY"


class Book:
    """Only local simulation. No API keys, no exchange trade endpoints."""
    def __init__(self, folder=ROOT, now=None):
        self.folder = Path(folder)
        self.state_path = self.folder / STATE_PATH.name
        self.log_path = self.folder / LOG_PATH.name
        self.lock = threading.RLock()
        self.now = utc_ms if now is None else now
        self.bot_started_ms = self.now()
        self.info = {"status": "BAGLANIYOR", "error": None,
                     "updated_at": None, "next_4h_at": None}
        self.prices = {}
        self.telegram = self._load_telegram()
        loaded = self.state_path.exists()
        if loaded:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            if saved.get("version") != 9:
                raise RuntimeError("Eski kayit farkli surum; verileri silmedim")
            self.accounts = saved["accounts"]
            self.technical = saved.get("technical", {"open": [], "history": []})
            if self.technical.get("open"):
                self.technical["open"] = []
                self.technical["history"].append({
                    "symbol": "TEST", "net": None,
                    "reason": "BOT_KAPANDI_SONUC_DOGRULANAMADI",
                    "closed_at": iso(self.now())})
        else:
            self.accounts = {
                sym: {"equity": SEED, "peak": SEED, "worst_dd": 0.,
                      "wins": 0, "losses": 0, "closed": 0,
                      "unverified": 0, "position": None,
                      "last_bar": fresh_4h(self.now()),
                      "last_quote_at": None, "last_signal": None,
                      "last_reason": "Yeni 4H mum bekleniyor", "next_id": 1}
                for sym in SYMBOLS}
            self.technical = {"open": [], "history": []}
        if FAST_ID not in self.accounts:
            self.accounts[FAST_ID] = {
                "equity": SEED, "peak": SEED, "worst_dd": 0.,
                "wins": 0, "losses": 0, "closed": 0,
                "unverified": 0, "position": None,
                "last_bar": fresh_15m(self.now()), "last_quote_at": None,
                "last_signal": None, "last_reason": "15m kapanisi bekleniyor",
                "next_id": 1}
        if QUICK_ID not in self.accounts:
            self.accounts[QUICK_ID] = {
                "equity": SEED, "peak": SEED, "worst_dd": 0.,
                "wins": 0, "losses": 0, "closed": 0,
                "unverified": 0, "position": None,
                "last_bar": fresh_15m(self.now()), "last_quote_at": None,
                "last_signal": None, "last_reason": "Hizli sanal giris bekleniyor",
                "next_id": 1, "next_allowed_ms": 0,
                "entry_day": "", "entries_today": 0,
            }
        if loaded:
            for sym in (*SYMBOLS, FAST_ID, QUICK_ID):
                acc = self.accounts[sym]
                if acc["position"] is not None:
                    p = acc["position"]
                    self._log("DOGRULANAMADI", sym, p, None, None,
                              "Program yeniden basladi, ara fiyatlar bilinmiyor")
                    acc["unverified"] += 1
                    acc["position"] = None
                    self._notify(sym + " SANAL POZISYON DOGRULANAMADI: "
                                 "Bot durmustu; kar veya zarar yazilmadi.")
        self.save()


    def on_quick_ready(self, bars, now, price, quote_at):
        """Experimental immediate PAPER trade, separate from research strategies."""
        with self.lock:
            acc = self.accounts[QUICK_ID]
            if acc["position"] is not None or now < acc.get("next_allowed_ms", 0):
                return False
            day = dt.datetime.fromtimestamp(now/1000, dt.timezone.utc).strftime("%Y-%m-%d")
            if acc.get("entry_day") != day:
                acc["entry_day"] = day
                acc["entries_today"] = 0
            if acc["entries_today"] >= QUICK_DAILY_CAP:
                acc["last_reason"] = "Gunluk 8 hizli sanal islem limiti doldu"
                return False
            if len(bars) < 35 or bars[-1][0] != fresh_15m(now):
                return False
            if price is None or not math.isfinite(price) or price <= 0:
                return False
            if quote_at is None or not -CLOCK_SKEW_MS <= now - quote_at <= FRESH_TICK_MS:
                return False
            if any(y[0]-x[0] != FIFTEEN for x,y in zip(bars,bars[1:])):
                return False
            closes = [r[4] for r in bars]
            current_atr = atr(bars)
            if not math.isfinite(current_atr) or current_atr <= 0:
                return False
            # A quick exercise starts without a rare breakout/crossover trigger.
            # Direction is based ONLY on completed 15-minute candles.
            direction = 1 if ema(closes,8)[-1] >= ema(closes,21)[-1] else -1
            entry = price * (1 + direction * SLIP)
            distance = max(1.5 * current_atr, price * .001)
            if distance >= price * .08:
                return False
            stop = entry - direction * distance
            target = entry + direction * 1.5 * distance
            cost_buffer = 2 * entry * (FEE + SLIP)
            quantity = min(acc["equity"]/entry,
                           acc["equity"] * RISK / (distance + cost_buffer))
            if not 0 < quantity * entry <= acc["equity"] + .01:
                return False
            p = {
                "id": f"{QUICK_ID}-{acc['next_id']:05d}",
                "direction": direction, "entry": entry, "quantity": quantity,
                "stop": stop, "target": target,
                "opened_ms": now, "deadline_ms": now + QUICK_HOLD_MS,
                "strategy": "BTC 15m EMA8/21 HIZLI DENEYSEL",
                "signal_at": bars[-1][0] + FIFTEEN,
            }
            acc["position"] = p
            acc["next_id"] += 1
            acc["entries_today"] += 1
            acc["next_allowed_ms"] = now + QUICK_REENTRY_MS
            acc["last_bar"] = bars[-1][0]
            acc["last_signal"] = iso(now)
            acc["last_reason"] = "HIZLI SANAL LONG acildi" if direction == 1 else "HIZLI SANAL SHORT acildi"
            self._log("SANAL_ACILIS", QUICK_ID, p, None, None,
                      "Deneysel hizli islem; karlilik kanitlanmadi")
            self.save()
            self._notify(
                f"BTC HIZLI DENEYSEL SANAL {'LONG' if direction == 1 else 'SHORT'} ACILDI\\n"
                f"Giris: {entry:.2f} | Stop: {stop:.2f} | Hedef: {target:.2f}\\n"
                "5 dakika sonra veya stop/hedefte kapanir. GERCEK EMIR YOK.")
            return True

    def _load_telegram(self):
        # Reuse previous bot's PC-only Telegram config without asking for keys,
        # copying secrets to a new folder, or uploading them anywhere.
        home = Path.home()
        roots = [self.folder,
                 home / "Desktop", home / "Masaüstü",
                 home / "Downloads", home / "İndirilenler",
                 home / "OneDrive" / "Desktop",
                 home / "OneDrive" / "Masaüstü"]
        scanned = set()
        for folder in roots:
            for pattern in ("pc_telegram_ayar.json",
                            "*/pc_telegram_ayar.json",
                            "*/*/pc_telegram_ayar.json"):
                try:
                    matches = folder.glob(pattern)
                    for candidate in matches:
                        if not candidate.is_file() or candidate in scanned:
                            continue
                        scanned.add(candidate)
                        try:
                            x = json.loads(candidate.read_text(encoding="utf-8"))
                            if x.get("token") and x.get("chat_id"):
                                return {"token": x["token"],
                                        "chat_id": x["chat_id"]}
                        except (OSError, ValueError, TypeError):
                            continue
                except OSError:
                    continue
        return {}

    def _notify(self, message):
        cfg = self.telegram
        if not cfg:
            return
        try:
            payload = urllib.parse.urlencode({
                "chat_id": cfg["chat_id"], "text": message}).encode()
            req = urllib.request.Request(
                "https://api.telegram.org/bot" + cfg["token"] + "/sendMessage",
                data=payload, headers={"User-Agent": "BitgetPaperV9"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                response = json.load(resp)
            if not response.get("ok"):
                raise RuntimeError("Telegram red")
        except Exception as exc:
            print("Telegram gonderilemedi:", type(exc).__name__, flush=True)

    def _log(self, event, symbol, p, price, net, reason):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", newline="") as handle:
            if handle.tell() == 0:
                handle.write("\ufeff")  # one Excel BOM only, not one per append
                w = csv.writer(handle, delimiter=";")
                w.writerow(["Zaman UTC", "Olay", "Coin", "Yon",
                            "Giris USDT", "Cikis USDT", "Net USDT",
                            "Sebep", "Sanal ID"])
            w = csv.writer(handle, delimiter=";")
            w.writerow([iso(self.now()), event, symbol,
                        "LONG" if p["direction"] == 1 else "SHORT",
                        round(p["entry"], 4),
                        round(price, 4) if price is not None else "",
                        round(net, 4) if net is not None else "", reason, p["id"]])

    def save(self):
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"version": 9, "accounts": self.accounts,
                                   "technical": self.technical},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def snapshot(self):
        with self.lock:
            moment = self.now()
            diagnostics = {
                sym: {
                    "age_seconds": (
                        round(max(0, moment - acc["last_quote_at"]) / 1000, 1)
                        if acc.get("last_quote_at") is not None else None
                    ),
                    "last_tick_utc": (iso(acc["last_quote_at"])
                                      if acc.get("last_quote_at") else None),
                    "fresh": (
                        -CLOCK_SKEW_MS <= moment - acc["last_quote_at"] <= MAX_TICK_GAP_MS
                        if acc.get("last_quote_at") is not None else False
                    )
                }
                for sym, acc in self.accounts.items()
            }
            return {
                "version": VERSION, "now_utc": iso(moment),
                "diagnostics": diagnostics,
                "status": dict(self.info),
                "quotes": {s: self.prices.get(s) for s in SYMBOLS},
                "accounts": json.loads(json.dumps(self.accounts)),
                "historical_research": RESEARCH,
                "experimental_research": {
                    "BTC15M": {"first_40d_pct": 9.4,
                               "recent_40d_pct": 2.223,
                               "recent_closed_trades": 30,
                               "double_cost_pct": -1.725,
                               "caveat": "Deneysel; 2 kat maliyette ZARARLI."}},
                "technical": json.loads(json.dumps(self.technical)),
                "telegram_active": bool(self.telegram),
                "csv_file": self.log_path.name
            }

    def on_quote(self, symbol, raw, stamp, now=None):
        now = self.now() if now is None else now
        if symbol not in SYMBOLS or not math.isfinite(raw) or raw <= 0:
            return
        # A small exchange/server clock offset must not freeze the entire UI.
        # Never accept prices older than 60 seconds.
        if not -CLOCK_SKEW_MS <= now - stamp <= FRESH_TICK_MS:
            return
        with self.lock:
            account = self.accounts[symbol]
            self.prices[symbol] = {"price": raw, "timestamp": iso(stamp)}
            position = account["position"]
            old_quote = account.get("last_quote_at")
            if position is not None and old_quote and now - old_quote > MAX_TICK_GAP_MS:
                self._log("DOGRULANAMADI", symbol, position, None, None,
                          "Canli veri 3 dakikadan fazla kesildi")
                account["unverified"] += 1
                account["position"] = None
                account["last_reason"] = "Veri kesildi, islem sonucu belirsiz"
                self._notify(symbol + " SANAL TAKIP DURAKLADI: fiyat araligi "
                             "belirsiz, kar/zarar hesaplanmadi.")
            account["last_quote_at"] = stamp
            if symbol == "BTCUSDT":
                quick = self.accounts[QUICK_ID]
                qp = quick["position"]
                old_quick_tick = quick.get("last_quote_at")
                if qp and old_quick_tick and now - old_quick_tick > MAX_TICK_GAP_MS:
                    self._log("DOGRULANAMADI", QUICK_ID, qp, None, None,
                              "Hizli sanal takip veri boslugu")
                    quick["unverified"] += 1
                    quick["position"] = None
                    quick["last_reason"] = "Veri kesildi; kar/zarar bilinmiyor"
                quick["last_quote_at"] = stamp
                qp = quick["position"]
                if qp:
                    d = qp["direction"]
                    hit_stop = raw <= qp["stop"] if d == 1 else raw >= qp["stop"]
                    hit_target = raw >= qp["target"] if d == 1 else raw <= qp["target"]
                    if hit_stop:
                        self._close(QUICK_ID,
                                    min(raw, qp["stop"]) if d == 1 else max(raw, qp["stop"]),
                                    "HIZLI STOP", now)
                    elif hit_target:
                        self._close(QUICK_ID, qp["target"], "HIZLI HEDEF", now)
                    elif now >= qp["deadline_ms"]:
                        self._close(QUICK_ID, raw, "HIZLI 5 DAKIKA", now)
                fast = self.accounts[FAST_ID]
                fp = fast["position"]
                old_fast_tick = fast.get("last_quote_at")
                if fp and old_fast_tick and now-old_fast_tick>MAX_TICK_GAP_MS:
                    self._log("DOGRULANAMADI", FAST_ID, fp, None, None,
                              "15m fiyat akisi kesildi")
                    fast["unverified"] += 1
                    fast["position"] = None
                    fast["last_reason"] = "15m ara fiyatlar kayip"
                fast["last_quote_at"] = stamp
                fp = fast["position"]
                if fp:
                    d = fp["direction"]
                    hit = (raw<=fp["stop"] if d==1 else raw>=fp["stop"])
                    if hit:
                        fill_raw=min(raw,fp["stop"]) if d==1 else max(raw,fp["stop"])
                        self._close(FAST_ID,fill_raw,"15m STOP",now)
                    elif now>=fp["deadline_ms"]:
                        self._close(FAST_ID,raw,"15m 168 SAAT",now)
            remaining = []
            for test in self.technical["open"]:
                if test["symbol"]!=symbol or now<test["deadline_ms"]:
                    remaining.append(test)
                    continue
                d=test["direction"]
                fill=raw*(1-d*SLIP)
                net=(fill-test["entry"])*d*test["quantity"]
                net-=FEE*(test["entry"]+fill)*test["quantity"]
                outcome={"symbol":symbol,"direction":d,
                         "entry":round(test["entry"],4),
                         "exit":round(fill,4),"net":round(net,4),
                         "reason":"90 SN TEKNIK TEST","closed_at":iso(now)}
                self.technical["history"].append(outcome)
                self.technical["history"]=self.technical["history"][-12:]
                print("SANAL TEKNIK TEST KAPANDI",outcome,flush=True)
            self.technical["open"]=remaining
            position = account["position"]
            if position:
                d = position["direction"]
                hit = (raw <= position["stop"] if d == 1
                       else raw >= position["stop"])
                expired = now >= position["deadline_ms"]
                if hit:
                    worst_price = (min(raw, position["stop"]) if d == 1
                                   else max(raw, position["stop"]))
                    self._close(symbol, worst_price, "STOP", now)
                elif expired:
                    self._close(symbol, raw, "30 GUN SURE", now)
            self.save()

    def _close(self, symbol, raw, reason, now):
        acc = self.accounts[symbol]
        p = acc["position"]
        if p is None:
            return
        d = p["direction"]
        fill = raw * (1 - d * SLIP)
        qty = p["quantity"]
        gross = (fill - p["entry"]) * d * qty
        costs = FEE * (fill + p["entry"]) * qty
        net = gross - costs
        acc["equity"] += net
        acc["peak"] = max(acc["peak"], acc["equity"])
        acc["worst_dd"] = min(acc["worst_dd"],
                              100 * (acc["equity"]/acc["peak"] - 1))
        acc["closed"] += 1
        acc["wins" if net > 0 else "losses"] += 1
        acc["position"] = None
        acc["last_reason"] = ("Sanal " + ("KAR " if net > 0 else "ZARAR ")
                              + f"{net:+.3f} USDT")
        self._log("SANAL_KAPANIS", symbol, p, fill, net, reason)
        self.save()
        msg = (f"{symbol} SANAL {'LONG' if d == 1 else 'SHORT'} KAPANDI\n"
               f"Giris: {p['entry']:.2f}, Cikis: {fill:.2f}\n"
               f"NET (tahmini masraf dahil): {net:+.3f} USDT\n"
               f"Sanal bakiye: {acc['equity']:.2f} USDT\n"
               f"Sebep: {reason} | GERCEK EMIR YOK")
        print(msg, flush=True)
        self._notify(msg)

    def start_technical_test(self):
        """Manual 90-second real-ticker test; never counted as strategy PnL."""
        with self.lock:
            if self.technical["open"]:
                return False, "Test zaten devam ediyor"
            now=self.now()
            tests=[]
            for sym,d in (("BTCUSDT",1),("ETHUSDT",-1)):
                q=self.prices.get(sym)
                stamp=self.accounts[sym].get("last_quote_at")
                if not q or stamp is None or not -CLOCK_SKEW_MS<=now-stamp<=FRESH_TICK_MS:
                    return False, sym+" guncel fiyat bekleniyor"
                entry=q["price"]*(1+d*SLIP)
                tests.append({"symbol":sym,"direction":d,"entry":entry,
                              "quantity":100.0/entry,"opened_ms":now,
                              "deadline_ms":now+TECH_DURATION_MS})
            self.technical["open"]=tests
            self.save()
            print("90 SN SANAL TEKNIK TEST ACILDI: BTC LONG, ETH SHORT",flush=True)
            return True, "BTC LONG + ETH SHORT 90 saniyelik sanal teknik test basladi"

    def on_fast_15m_close(self,bars,now,price,quote_at):
        with self.lock:
            acc=self.accounts[FAST_ID]
            newest=bars[-1][0]
            if newest<=acc["last_bar"]:
                return
            if newest!=fresh_15m(now):
                raise RuntimeError("Bitget BTC 15m mum kapanisi eksik")
            if now-(newest+FIFTEEN)>MAX_SIGNAL_DELAY_MS:
                acc["last_bar"]=newest
                acc["last_reason"]="15m gecmis mum atlandi; yeni emir uydurulmadi"
                self.save()
                return
            ev,reason=fast_signal_from_closed(bars)
            acc["last_bar"]=newest
            acc["last_reason"]=reason
            if acc["position"] is not None:
                p=acc["position"]
                updated=bars[-1][4]-p["direction"]*p["trail_atr"]*atr(bars)
                p["stop"]=max(p["stop"],updated) if p["direction"]==1 else min(p["stop"],updated)
                self.save()
                return
            if ev is None:
                self.save()
                return
            if (price is None or quote_at is None or
                not -CLOCK_SKEW_MS<=now-quote_at<=FRESH_TICK_MS):
                acc["last_reason"]="15m sinyal var, taze fiyat yok"
                self.save()
                return
            if abs(price-ev["reference"])>.5*ev["atr"]:
                acc["last_reason"]="15m sinyal, giris fiyati cok uzak"
                self.save()
                return
            d=ev["direction"]
            fill=price*(1+d*SLIP)
            distance=(fill-ev["stop"])*d
            if distance<=0 or acc["equity"]<=0:
                acc["last_reason"]="15m sanal risk gecersiz"
                self.save()
                return
            qty=min(acc["equity"]*RISK/distance,
                    acc["equity"]*MAX_NOTIONAL/fill)
            if qty<=0:
                acc["last_reason"]="15m hesapta sanal pozisyon acilamadi"
                self.save()
                return
            p={"id":f"{FAST_ID}-{acc['next_id']:05d}",
               "direction":d,"entry":fill,"quantity":qty,
               "stop":ev["stop"],"trail_atr":ev["trail_atr"],
               "opened_ms":now,"deadline_ms":now+168*60*60*1000,
               "strategy":"BTC 15DK DONCHIAN55 DENEYSEL",
               "signal_at":ev["signal_at"]}
            acc["next_id"]+=1
            acc["position"]=p
            acc["last_signal"]=iso(now)
            acc["last_reason"]="15m otomatik sanal emir ACILDI"
            self._log("SANAL_ACILIS",FAST_ID,p,None,None,p["strategy"])
            self.save()
            msg=(f"BTC 15DK DENEYSEL SANAL {'LONG' if d==1 else 'SHORT'} ACILDI\n"
                 f"Giris: {fill:.2f} / Stop: {ev['stop']:.2f}\n"
                 f"Nominal: {qty*fill:.2f} USDT\n"
                 "Gercek emir YOK. 2x maliyet tarihi testte ZARAR.")
            print(msg,flush=True)
            self._notify(msg)

    def on_4h_close(self, symbol, bars, days, now, price, quote_at):
        with self.lock:
            acc = self.accounts[symbol]
            latest = bars[-1][0]
            if latest <= acc["last_bar"]:
                return
            if latest != fresh_4h(now):
                raise RuntimeError("Son 4H kapanis mumu henuz Bitget API'de yok")
            decision_time = latest + FOUR
            # Decline any late replay rather than silently opening trades.
            if now - decision_time > MAX_SIGNAL_DELAY_MS:
                acc["last_bar"] = latest
                acc["last_reason"] = "Yeni 4H kapanisi bekleniyor (eski emir acilmadi)"
                self.save()
                return
            ev, reason = signal_from_closed(symbol, bars, days)
            acc["last_bar"] = latest
            acc["last_reason"] = reason
            if acc["position"] is not None:
                # Trailing update only AFTER the signal candle has CLOSED.
                p = acc["position"]
                updated = bars[-1][4] - p["direction"] * p["trail_atr"] * atr(bars)
                p["stop"] = max(p["stop"], updated) if p["direction"] == 1 \
                    else min(p["stop"], updated)
                self.save()
                return
            if not ev:
                self.save()
                return
            if (price is None or quote_at is None or
                    not -CLOCK_SKEW_MS <= now-quote_at <= FRESH_TICK_MS):
                acc["last_reason"] = "Sinyal var, guncel fiyat yok"
                self.save()
                return
            if abs(price - ev["reference"]) > .5 * ev["atr"]:
                acc["last_reason"] = "Sinyal var, giris fiyati cok uzak"
                self.save()
                return
            d = ev["direction"]
            fill = price * (1 + d * SLIP)
            risk = (fill - ev["stop"]) * d
            if risk <= 0:
                acc["last_reason"] = "Stop mesafesi gecersiz"
                self.save()
                return
            capital = acc["equity"]
            qty = min(capital * RISK / risk,
                      capital * MAX_NOTIONAL / fill)
            if qty <= 0:
                acc["last_reason"] = "Pozisyon boyutu gecersiz"
                self.save()
                return
            pos = {
                "id": f"{symbol}-{acc['next_id']:05d}",
                "direction": d, "entry": fill, "quantity": qty,
                "stop": ev["stop"], "trail_atr": ev["trail_atr"],
                "opened_ms": now, "deadline_ms": now + 30 * DAY,
                "strategy": RESEARCH[symbol]["strategy"],
                "signal_at": ev["signal_at"]
            }
            acc["next_id"] += 1
            acc["position"] = pos
            acc["last_signal"] = iso(now)
            acc["last_reason"] = "Sanal pozisyon acildi"
            self._log("SANAL_ACILIS", symbol, pos, None, None,
                      RESEARCH[symbol]["strategy"])
            self.save()
            msg = (f"{symbol} SANAL {'LONG' if d == 1 else 'SHORT'} ACILDI\n"
                   f"Giris: {fill:.2f} USDT | Stop: {ev['stop']:.2f}\n"
                   f"Nominal: {qty*fill:.2f} USDT (maks 1x)\n"
                   f"4H Donchian | GERCEK EMIR YOK\n"
                   "Strateji karliligi garanti degildir.")
            print(msg, flush=True)
            self._notify(msg)


PAGE = r"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC ETH Sanal Islem Paneli</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#e9f2f9;background:#0d1522}
*{box-sizing:border-box}body{margin:0;padding:27px;max-width:1150px;margin:auto}
h1{font-size:24px;margin:0 0 6px}h2{font-size:17px;margin:0 0 14px}p{line-height:1.5}
.muted{color:#9aacbd}.small{font-size:13px}.tag{display:inline-block;padding:6px 11px;border-radius:30px;background:#163c31;color:#73ddb5;font-weight:650;font-size:12px}
.top{display:flex;justify-content:space-between;align-items:start;gap:14px;margin-bottom:22px;flex-wrap:wrap}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(285px,1fr));gap:16px}
.card{background:#172332;border:1px solid #304153;border-radius:17px;padding:19px}
.money{font-weight:750;font-size:31px;font-variant-numeric:tabular-nums}
.green{color:#67dfa7}.red{color:#ff8a92}.label{color:#9aacbd;font-size:13px}
hr{border:0;border-top:1px solid #304153;margin:19px 0}
.row{display:flex;justify-content:space-between;gap:15px;margin:8px 0;align-items:center}
.data{font-size:14px}strong{font-variant-numeric:tabular-nums}
.note{padding:14px 17px;background:#202b37;border-radius:12px;color:#d4dde7}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;border-bottom:1px solid #304153;padding:10px 7px}
th{color:#9aacbd;font-weight:500}.foot{margin-top:18px;font-size:12px;color:#95a7b8}
button{cursor:pointer;color:#fff;background:#304e67;border:0;border-radius:9px;padding:8px 13px}
@media(max-width:540px){body{padding:15px}h1{font-size:20px}.money{font-size:26px}}
</style></head>
<body>
<div class="top"><div><h1>Bitget BTC + ETH | Sanal Islem Paneli <span class="muted small">V9.2</span></h1>
<div class="muted small">Gercek hesap baglantisi yok. Para kullanilmaz, borsaya emir gitmez.</div></div>
<div><span class="tag" id="stat">Baglaniyor</span><div class="small muted" id="refreshed"></div><div class="small muted" id="nextcheck"></div><div class="small muted" id="healthinfo"></div></div></div>
<div class="grid" id="coins"><div class="card">Bitget verisi bekleniyor...</div></div>
<div style="height:18px"></div>
<div class="grid">
 <div class="card">
  <h2>BTC 15 dakika | DENEYSEL otomatik sanal bot</h2>
  <p class="muted small">BTC icin ayri 15DK sanal hesap. Islem kosullari olusunca otomatik LONG/SHORT acar.</p>
  <div id="fast">15 dakikalik mumlar taraniyor...</div><p class="small muted" id="fastnext"></p>
 </div>
 <div class="card">
  <h2>Sanal teknik test</h2>
  <p class="muted small">90 saniyelik emir acma-kapama kontrolu. Strateji kârina eklenmez.</p>
  <button onclick="startTechnical()" id="technicalButton">90 SN SANAL TEST AC</button>
  <p id="tech" class="data muted">Henuz teknik test baslatilmadi.</p>
 </div>
</div>
<div class="small muted" style="margin-top:16px" id="tg"></div>
<div class="foot">Sanal fiyatlar Bitget USDT-FUTURES genel API'sinden. Tahmini komisyon %0,06 ve olumsuz fiyat kaymasi %0,03 her yon. Funding, gercek emir dolumu ve spread dahil degil. Kar garantisi bulunmaz.</div>
<script>
function n(x,d){return Number(x).toLocaleString('tr-TR',{minimumFractionDigits:d,maximumFractionDigits:d})}
function sign(x){return (x>=0?'+':'')+n(x,2)}
function dtfmt(x){try{return new Date(x).toLocaleString('tr-TR')}catch(e){return x}}
function sHtml(sym,d){
 let a=d.accounts[sym],q=d.quotes[sym],p=a.position;let diff=a.equity-1000;
 let latest=(a.last_reason||'').replace('Eski mum atlandi, gecmis emir acilmadi','Yeni 4H kapanisi bekleniyor');
 let cls=diff>=0?'green':'red';let price=q?n(q.price,2)+' USDT':'Veri bekleniyor';
 return '<div class="card"><div class="row"><h2>'+sym+'</h2><span class="muted small">'+(sym==='BTCUSDT'?'Donchian20 4H':'Donchian55 4H')+'</span></div>'
 +'<div class="label">Canli Bitget fiyati</div><div class="money">'+price+'</div>'
 +'<hr><div class="row"><span class="label">Sanal bakiye</span><strong>'+n(a.equity,2)+' USDT</strong></div>'
 +'<div class="row"><span class="label">Net sanal kar / zarar</span><strong class="'+cls+'">'+sign(diff)+' USDT</strong></div>'
 +'<div class="row"><span class="label">Kapanan / kazanan / kaybeden</span><strong>'+a.closed+' / '+a.wins+' / '+a.losses+'</strong></div>'
 +'<div class="row"><span class="label">Dogrulanamayan</span><strong>'+a.unverified+'</strong></div><hr>'
 +(p?'<div class="tag">SANAL '+(p.direction===1?'LONG':'SHORT')+' ACIK</div>'
 +'<p class="data">Giris: <strong>'+n(p.entry,2)+'</strong> | Stop: <strong>'+n(p.stop,2)+'</strong></p>'
 :'<div class="muted">Suan acik sanal pozisyon yok.</div>')
 +'<p class="muted small">Son kontrol: '+latest+'</p></div>';
}
async function render(){
 try{
 const r=await fetch('/api/state',{cache:'no-store'});
 if(!r.ok)throw Error('baglanti');
 const d=await r.json();
 document.getElementById('stat').textContent=d.status.status;
 document.getElementById('refreshed').textContent='Son yenileme: '+dtfmt(d.now_utc);
 document.getElementById('nextcheck').textContent='Sonraki 4H mum: '+dtfmt(d.status.next_4h_at);
 document.getElementById('healthinfo').textContent=['BTCUSDT','ETHUSDT'].map(s=>s.replace('USDT','')+': '+(d.diagnostics[s].age_seconds===null?'fiyat gelmedi':d.diagnostics[s].age_seconds+' sn')).join(' | ') + (d.status.error ? ' | HATA: '+d.status.error : '');
 document.getElementById('coins').innerHTML=['BTCUSDT','ETHUSDT'].map(s=>sHtml(s,d)).join('');
 const a=d.accounts.BTC15M,p=a.position,net=a.equity-1000;
 document.getElementById('fastnext').textContent='Sonraki 15DK kapanisi: '+dtfmt(d.status.next_15m_at);
 document.getElementById('fast').innerHTML=
  '<div class="row"><span class="label">Sanal bakiye</span><strong>'+n(a.equity,2)+' USDT</strong></div>'
  +'<div class="row"><span class="label">Gerceklesen sanal net</span><strong class="'+(net>=0?'green':'red')+'">'+sign(net)+' USDT</strong></div>'
  +'<div class="row"><span class="label">Kapanan / kazanan / kaybeden</span><strong>'+a.closed+' / '+a.wins+' / '+a.losses+'</strong></div>'
  +(p?'<p class="tag">15DK SANAL '+(p.direction===1?'LONG':'SHORT')+' ACIK</p><p>Giris: '+n(p.entry,2)+' | Stop: '+n(p.stop,2)+'</p>':'<p class="muted">15DK strateji sinyali bekleniyor.</p>')
  +'<p class="muted small">Son kontrol: '+a.last_reason+'</p>';
 const tech=d.technical;
 const outs=tech.history.slice(-4).reverse().map(x=>
  x.net===null?'<div class="small muted">'+x.reason+'</div>':
  '<div class="small '+(x.net>=0?'green':'red')+'">'+x.symbol+' '+(x.direction===1?'LONG':'SHORT')+': '+sign(x.net)+' USDT ('+n(x.entry,2)+' → '+n(x.exit,2)+')</div>').join('');
 document.getElementById('tech').innerHTML=
  (tech.open.length?
   '<strong class="green">ACIK: '+tech.open.map(x=>x.symbol+' '+(x.direction===1?'LONG':'SHORT')+' | '+Math.max(0,Math.ceil((x.deadline_ms-Date.now())/1000))+' sn').join(' / ')+'</strong><p class="muted small">Gercek Bitget fiyatlariyla kapanis bekleniyor.</p>':
    '<span class="muted">Su an acik teknik test yok.</span>')
   +(outs?'<hr>'+outs:'');
 document.getElementById('technicalButton').disabled=tech.open.length>0;
 document.getElementById('tg').textContent=d.telegram_active?'Telegram: onceki klasordeki ayarlar kullaniliyor.':'Telegram: bu klasorde ayar dosyasi yok; panel ve CSV kaydi yine calisir.';
 }catch(e){document.getElementById('stat').textContent='Baglanti bekleniyor'}
}
async function startTechnical(){
 const b=document.getElementById('technicalButton');
 b.disabled=true;
 try{
  const r=await fetch('/api/test',{method:'POST',
    headers:{'Content-Type':'application/json'},body:'{}'});
  const result=await r.json();
  document.getElementById('tech').textContent=result.message;
 }catch(e){document.getElementById('tech').textContent='Baglanti hatasi: '+String(e)}
 await render();
}
render();setInterval(render,5000);
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    book = None

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route not in ("/", "/api/state"):
            self.send_error(404)
            return
        # A versioned URL forces a fresh HTML document, rather than leaving
        # the user's previous V9.1 Chrome tab open on its old JS bundle.
        content = (PAGE.encode("utf-8") if route == "/" else
                   json.dumps(self.book.snapshot(), ensure_ascii=False)
                   .encode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", ("text/html" if route == "/" else
                                         "application/json") + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if (self.path != "/api/test" or
                self.headers.get("Content-Type", "").split(";")[0] != "application/json"):
            self.send_error(404)
            return
        origin=self.headers.get("Origin")
        if origin and origin != "http://127.0.0.1:%d" % PORT:
            self.send_error(403)
            return
        ok,message=self.book.start_technical_test()
        data=json.dumps({"ok":ok,"message":message},
                        ensure_ascii=False).encode("utf-8")
        self.send_response(200 if ok else 409)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


def main():
    print("\nBITGET SANAL PANEL V9.2 - GERCEK EMIR GONDERMEZ", flush=True)
    print("Bitget public BTC ETH verisi | BTC Donchian20 / ETH Donchian55 4H", flush=True)
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print("Panel zaten acik olabilir: http://127.0.0.1:%d" % PORT)
        webbrowser.open_new_tab("http://127.0.0.1:%d/?v=9.2" % PORT)
        return
    # Lock port BEFORE loading state: second launcher must not mark an
    # already running paper position as unverified and overwrite disk state.
    try:
        book = Book()
    except Exception:
        server.server_close()
        raise
    Handler.book = book
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("PANEL: http://127.0.0.1:%d/" % PORT, flush=True)
    print("Excel islemler: %s" % LOG_PATH.name, flush=True)
    threading.Thread(target=lambda: webbrowser.open_new_tab(
        "http://127.0.0.1:%d/?v=9.2&fresh=%d" % (PORT, int(time.time()))),
        daemon=True).start()
    daily_cache = {}
    next_tickers = 0
    next_scan = 0
    next_fast_scan = 0
    # A one-time, explicitly labeled paper execution demonstration.
    # Never repeat after it finishes or becomes unverifiable, and never
    # credit its PnL to an automated trading strategy or account.
    startup_technical_pending = not (
        book.technical.get("open") or book.technical.get("history"))
    while True:
        now = utc_ms()
        with book.lock:
            book.info["next_4h_at"] = iso(((now // FOUR) + 1) * FOUR)
            book.info["next_15m_at"] = iso(((now // FIFTEEN) + 1) * FIFTEEN)
        try:
            if now >= next_tickers:
                next_tickers = now + 20_000
                tick_errors = []
                for sym in SYMBOLS:
                    try:
                        px, stamp = ticker(sym)
                        book.on_quote(sym, px, stamp, now=utc_ms())
                    except Exception as exc:
                        tick_errors.append(sym + ": " + str(exc)[:100])
                        print("Fiyat kontrolu:", sym, type(exc).__name__, str(exc)[:120], flush=True)
                with book.lock:
                    book.info["error"] = " | ".join(tick_errors) if tick_errors else None
                    if len(book.prices) == len(SYMBOLS):
                        book.info["updated_at"] = iso(utc_ms())
                if startup_technical_pending:
                    started, why = book.start_technical_test()
                    if started:
                        startup_technical_pending = False
                        print("OTO TEKNIK TEST: 90 saniye sonra sadece "
                              "sanal LONG/SHORT sonuclari gorunecek.", flush=True)
            if now >= next_fast_scan:
                next_fast_scan = now + 8_000
                if fresh_15m(now) > book.accounts[FAST_ID]["last_bar"]:
                    try:
                        bars = recent_closed_fifteen(utc_ms())
                        quote = book.prices.get("BTCUSDT")
                        stamp = book.accounts["BTCUSDT"].get("last_quote_at")
                        book.on_fast_15m_close(
                            bars,utc_ms(),quote["price"] if quote else None,stamp)
                    except Exception as exc:
                        with book.lock:
                            book.info["error"] = "BTC 15m: " + str(exc)[:110]
                        print("BTC 15m kontrol:",type(exc).__name__,
                              str(exc)[:130],flush=True)
            if now >= next_scan:
                next_scan = now + 15_000
                for sym in SYMBOLS:
                    # On startup, do not generate retrospective trade signals.
                    # Fetch only on a NEW closed 4H candle.
                    if fresh_4h(now) <= book.accounts[sym]["last_bar"]:
                        continue
                    try:
                        bars = recent_closed_four(sym, utc_ms())
                        expected_last = fresh_4h(utc_ms())
                        if bars[-1][0] != expected_last:
                            raise RuntimeError("Bitget henuz kapanmis 4H mumu vermedi")
                        current_day = (utc_ms()//DAY)*DAY
                        if sym not in daily_cache or daily_cache[sym][0] != current_day:
                            daily_cache[sym] = (current_day, daily_closed(sym, utc_ms()))
                        quote = book.prices.get(sym)
                        latest_tick = book.accounts[sym].get("last_quote_at")
                        book.on_4h_close(sym, bars, daily_cache[sym][1], utc_ms(),
                                         quote["price"] if quote else None,
                                         latest_tick)
                    except Exception as exc:
                        with book.lock:
                            book.info["error"] = (sym + " 4H: " + str(exc)[:120])
                        print("4H kontrolu:", sym, type(exc).__name__,
                              str(exc)[:130], flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print("Izleme tekrar deneniyor:", type(exc).__name__, str(exc)[:160])
        # Re-read clock AFTER Bitget network requests. The timestamp captured
        # at the TOP of this loop may be earlier than a valid fetched tick,
        # incorrectly producing "VERI BEKLENIYOR" on a live connection.
        health_now = utc_ms()
        with book.lock:
            fresh = [book.accounts[s].get("last_quote_at") for s in SYMBOLS]
            book.info["status"] = (
                "CANLI SANAL TAKIP" if
                all(v is not None and -CLOCK_SKEW_MS <= health_now - v <= MAX_TICK_GAP_MS
                    for v in fresh)
                else "VERI BEKLENIYOR")
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSanal takip durduruldu. Kayitlar silinmedi.")
