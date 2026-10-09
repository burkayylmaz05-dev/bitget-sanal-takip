# -*- coding: utf-8 -*-
"""GitHub Actions scheduled entry point; only simulated trades."""
import datetime as dt
import hashlib
import os
import sys
from pathlib import Path
import bitget_sinyal_takip as b

PENDING = Path(__file__).resolve().parent / "bildirim_kuyrugu.json"
MAX_PENDING = 150

def load_pending():
    data = b.load_json(PENDING, [])
    if not isinstance(data, list):
        raise ValueError("Bildirim kuyrugu bozuk")
    return data

def enqueue(messages):
    queue = load_pending()
    for message in messages:
        if not message:
            continue
        uid = hashlib.sha256((dt.datetime.now(dt.timezone.utc).isoformat() + message).encode()).hexdigest()[:20]
        queue.append({"id": uid, "text": message})
    if len(queue) > MAX_PENDING:
        raise RuntimeError("Bildirim kuyrugu dolu, silinmedi")
    b.save_json(PENDING, queue)
    return len(messages)

def v2_tick(state, symbol):
    messages = []
    five = b.candles(symbol, "5m")
    if symbol in state["open"]:
        event = b.manage_paper(state, symbol, five)
        if event:
            messages.append(
                f"SANAL ISLEM KAPANDI {symbol} {event['outcome']}\n"
                f"Tahmini net sonuc: {event['net_pnl_usdt']:+.2f} USDT\n"
                f"Sanal bakiye: {state['equity']:.2f} USDT")
    if symbol in state["open"]:
        return messages
    candidate, trends, _ = b.analyze(symbol)
    if candidate is None:
        return messages
    key = f"{candidate['direction']}:{candidate['candle']}"
    if state["last_signal"].get(symbol) == key:
        return messages
    risk = max(0, state["equity"]) * b.RISK_FRACTION
    if risk <= 0:
        return messages
    candidate["risk_usdt"] = risk
    state["last_signal"][symbol] = key
    state["open"][symbol] = candidate
    b.record({"event": "OPEN", **candidate,
              "time_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
    messages.append(
        f"BITGET {symbol} {candidate['direction']} ADAY (sanal)\n"
        f"Referans {candidate['entry']:.2f} | Stop {candidate['stop']:.2f} | "
        f"Hedef {candidate['target']:.2f}\n"
        f"RSI {candidate['rsi']:.1f} | Hacim {candidate['volume_ratio']:.2f}x\n"
        f"Trend: {trends}. Gercek emir YOK.")
    return messages

def main():
    telegram_enabled = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    if not telegram_enabled:
        print("Telegram ayarlari henuz eklenmedi: SANAL TEST VE KAYIT DEVAM EDIYOR.")
    state = b.load_json(b.STATE, {"open": {}, "last_signal": {}, "equity": b.PAPER_EQUITY})
    ab_state = b.ab_validate_state(b.load_json(b.AB_STATE_FILE, b.ab_default_state()))
    if "open" not in state or "last_signal" not in state:
        raise RuntimeError("v2 durum dosyasi bozuk")
    messages = []
    success = 0
    try:
        four, five = b.ab_get_4h(), b.candles("BTCUSDT", "5m")
        needs_funding = any(ab_state["accounts"][k]["position"] for k in b.AB_METHODS)
        funds = b.ab_funding_records() if needs_funding else None
        messages.extend(b.ab_tick(ab_state, five, four, funds))
        weekly = b.ab_weekly_summary(ab_state)
        if weekly:
            messages.append(weekly)
        b.save_json(b.AB_STATE_FILE, ab_state)
        b.ab_report(ab_state)
        success += 1
    except Exception as exc:
        print("A/B kontrol basarisiz:", type(exc).__name__)
    for sym in b.SYMBOLS:
        try:
            messages.extend(v2_tick(state, sym))
            success += 1
        except Exception as exc:
            print(sym, "izleme basarisiz:", type(exc).__name__)
    b.save_json(b.STATE, state)
    if telegram_enabled:
        enqueue(messages)
    elif messages:
        print("Telegram kapali, bildirimler kuyruga kaydedilmedi:", len(messages))
    print("Kontroller:", success, "/ 3; bildirim:", len(messages))
    return 0 if success == 3 else 1

if __name__ == "__main__":
    sys.exit(main())
