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

VERSION = "9.0"
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "v9_sanal_durum.json"
LOG_PATH = ROOT / "v9_sanal_islemler.csv"
TELEGRAM_PATH = ROOT / "pc_telegram_ayar.json"
API = "https://api.bitget.com"
FOUR = 4 * 60 * 60 * 1000
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
        if self.state_path.exists():
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            if saved.get("version") != 9:
                raise RuntimeError("Eski kayit farkli surum; verileri silmedim")
            self.accounts = saved["accounts"]
            for sym in SYMBOLS:
                acc = self.accounts[sym]
                # Preserve pending trade but do not hallucinate unattended
                # stops and fills during downtime: mark as unresolved.
                if acc["position"] is not None:
                    p = acc["position"]
                    self._log("DOGRULANAMADI", sym, p, None, None,
                              "Bilgisayar kapaliyken fiyat yolu bilinmiyor")
                    acc["unverified"] = acc.get("unverified", 0) + 1
                    acc["position"] = None
                    self._notify(sym + " SANAL POZISYON DOGRULANAMADI: "
                                 "Bot durmustu; kar veya zarar yazilmadi.")
        else:
            self.accounts = {
                sym: {"equity": SEED, "peak": SEED, "worst_dd": 0.,
                      "wins": 0, "losses": 0, "closed": 0,
                      "unverified": 0, "position": None,
                      "last_bar": fresh_4h(self.now()),
                      "last_quote_at": None, "last_signal": None,
                      "last_reason": "Yeni 4H mum bekleniyor",
                      "next_id": 1}
                for sym in SYMBOLS}
        self.save()

    def _load_telegram(self):
        try:
            x = json.loads((self.folder / TELEGRAM_PATH.name)
                           .read_text(encoding="utf-8"))
            if x.get("token") and x.get("chat_id"):
                return {"token": x["token"], "chat_id": x["chat_id"]}
        except (FileNotFoundError, ValueError, OSError):
            pass
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
        with self.log_path.open("a", encoding="utf-8-sig", newline="") as handle:
            w = csv.writer(handle, delimiter=";")
            if handle.tell() == 0:
                w.writerow(["Zaman UTC", "Olay", "Coin", "Yon",
                            "Giris USDT", "Cikis USDT", "Net USDT",
                            "Sebep", "Sanal ID"])
            w.writerow([iso(self.now()), event, symbol,
                        "LONG" if p["direction"] == 1 else "SHORT",
                        round(p["entry"], 4),
                        round(price, 4) if price is not None else "",
                        round(net, 4) if net is not None else "", reason, p["id"]])

    def save(self):
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"version": 9, "accounts": self.accounts},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def snapshot(self):
        with self.lock:
            return {
                "version": VERSION, "now_utc": iso(self.now()),
                "status": dict(self.info),
                "quotes": {s: self.prices.get(s) for s in SYMBOLS},
                "accounts": json.loads(json.dumps(self.accounts)),
                "historical_research": RESEARCH,
                "telegram_active": bool(self.telegram),
                "csv_file": self.log_path.name
            }

    def on_quote(self, symbol, raw, stamp, now=None):
        now = self.now() if now is None else now
        if symbol not in SYMBOLS or not math.isfinite(raw) or raw <= 0:
            return
        if not 0 <= now - stamp <= FRESH_TICK_MS:
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
                acc["last_reason"] = "Eski mum atlandi, gecmis emir acilmadi"
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
            if price is None or quote_at is None or not 0 <= now-quote_at <= FRESH_TICK_MS:
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
<div class="top"><div><h1>Bitget BTC + ETH | Sanal Islem Paneli</h1>
<div class="muted small">Gercek hesap baglantisi yok. Para kullanilmaz, borsaya emir gitmez.</div></div>
<div><span class="tag" id="stat">Baglaniyor</span><div class="small muted" id="refreshed"></div></div></div>
<div class="grid" id="coins"><div class="card">Bitget verisi bekleniyor...</div></div>
<div style="height:18px"></div>
<div class="card"><h2>2026 gercek piyasa verisiyle tarihsel sanal test</h2>
<p class="muted small">Bu bolumdeki sonuclar gecmiste yapilan simülasyondur. Ustteki bakiye ve islemler ise yalnizca bu program acikken ileriye donuk birikir. Iki kat masraf testi dahildir.</p>
<div class="grid" id="research"></div></div>
<div style="height:18px"></div>
<div class="card"><h2>Neden su anda pozisyon acik olmayabilir?</h2>
<p>Bot sadece <strong>tamamlanan 4 saatlik mumlarda</strong> strateji sinyali arar. Veri veya trend kosullari yoksa emir uydurmaz. BTC Donchian20 2026'nin son ~4 ayinda 6, ETH Donchian55 3 tarihsel islem uretmisti; bu stratejiler sik islem yapmaz.</p>
<p class="note">Sanal kayitlar bilgisayarindaki <strong>v9_sanal_islemler.csv</strong> dosyasina yazilir. Excel ile acilabilir. Eski V8 kayitlari degistirilmez. Bilgisayar kapanirsa acik islem sonuclari dogrulanamadigi icin kar/zarar sayilmaz.</p>
<div class="small muted" id="tg"></div></div>
<div class="foot">Sanal fiyatlar Bitget USDT-FUTURES genel API'sinden. Tahmini komisyon %0,06 ve olumsuz fiyat kaymasi %0,03 her yon. Funding, gercek emir dolumu ve spread dahil degil. Kar garantisi bulunmaz.</div>
<script>
function n(x,d){return Number(x).toLocaleString('tr-TR',{minimumFractionDigits:d,maximumFractionDigits:d})}
function sign(x){return (x>=0?'+':'')+n(x,2)}
function dtfmt(x){try{return new Date(x).toLocaleString('tr-TR')}catch(e){return x}}
function sHtml(sym,d){
 let a=d.accounts[sym],q=d.quotes[sym],p=a.position;let diff=a.equity-1000;
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
 +'<p class="muted small">Son kontrol: '+a.last_reason+'</p></div>';
}
async function render(){
 try{
 const r=await fetch('/api/state',{cache:'no-store'});
 if(!r.ok)throw Error('baglanti');
 const d=await r.json();
 document.getElementById('stat').textContent=d.status.status;
 document.getElementById('refreshed').textContent='Son yenileme: '+dtfmt(d.now_utc);
 document.getElementById('coins').innerHTML=['BTCUSDT','ETHUSDT'].map(s=>sHtml(s,d)).join('');
 document.getElementById('research').innerHTML=['BTCUSDT','ETHUSDT'].map(s=>{
  const x=d.historical_research[s];
  return '<div><strong>'+s+'</strong><div class="row"><span class="label">Ocak-Mayis 2026 ('+x.jan_may_trades+' islem)</span><strong class="green">+%'+n(x.jan_may,2)+'</strong></div>'
 +'<div class="row"><span class="label">Haziran-Ekim 2026 ('+x.jun_oct_trades+' islem)</span><strong class="green">+%'+n(x.jun_oct,2)+'</strong></div>'
 +'<div class="row"><span class="label">Son donem 2x maliyet</span><strong class="green">+%'+n(x.double_cost,2)+'</strong></div><p class="muted small">'+x.caveat+'</p></div>'}).join('');
 document.getElementById('tg').textContent=d.telegram_active?'Telegram: onceki klasordeki ayarlar kullaniliyor.':'Telegram: bu klasorde ayar dosyasi yok; panel ve CSV kaydi yine calisir.';
 }catch(e){document.getElementById('stat').textContent='Baglanti bekleniyor'}
}
render();setInterval(render,5000);
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    book = None

    def do_GET(self):
        if self.path.split("?")[0] not in ("/", "/api/state"):
            self.send_error(404)
            return
        content = (PAGE.encode("utf-8") if self.path == "/" else
                   json.dumps(self.book.snapshot(), ensure_ascii=False)
                   .encode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", ("text/html" if self.path == "/" else
                                         "application/json") + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, fmt, *args):
        pass


def main():
    print("\nBITGET SANAL PANEL V9 - GERCEK EMIR GONDERMEZ", flush=True)
    print("Bitget public BTC ETH verisi | BTC Donchian20 / ETH Donchian55 4H", flush=True)
    book = Book()
    Handler.book = book
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print("Panel zaten acik olabilir: http://127.0.0.1:%d" % PORT)
        webbrowser.open("http://127.0.0.1:%d/" % PORT)
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("PANEL: http://127.0.0.1:%d/" % PORT, flush=True)
    print("Excel islemler: %s" % LOG_PATH.name, flush=True)
    threading.Thread(target=lambda: webbrowser.open(
        "http://127.0.0.1:%d/" % PORT), daemon=True).start()
    daily_cache = {}
    next_tickers = 0
    next_scan = 0
    while True:
        now = utc_ms()
        try:
            if now >= next_tickers:
                next_tickers = now + 20_000
                for sym in SYMBOLS:
                    try:
                        px, stamp = ticker(sym)
                        book.on_quote(sym, px, stamp, now=utc_ms())
                    except Exception as exc:
                        with book.lock:
                            book.info["error"] = (sym + ": " + str(exc)[:120])
                        print("Fiyat kontrolu:", sym, type(exc).__name__, str(exc)[:120])
                with book.lock:
                    if len(book.prices) == len(SYMBOLS):
                        book.info["status"] = "CANLI SANAL TAKIP"
                        book.info["updated_at"] = iso(now)
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
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSanal takip durduruldu. Kayitlar silinmedi.")
