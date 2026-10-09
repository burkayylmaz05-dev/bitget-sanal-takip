# -*- coding: utf-8 -*-
"""Bitget BTC/ETH v3: existing v2 alerts + independent BTC 4H EMA A/B forward paper test. Stdlib only; no orders."""
import datetime as dt
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'bitget_telegram_ayar.json'  # Same configuration as v1
STATE = ROOT / 'bitget_sinyal_v2_durum.json'
TRADES = ROOT / 'bitget_sanal_islemler_v2.jsonl'
BASE = 'https://api.bitget.com'
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
TF_MS = {'5m': 300000, '15m': 900000, '1H': 3600000, '4H': 14400000}
POLL_SECONDS = 300
# Estimates, not Bitget account-specific actual fees. Round-trip cost = 2*(fee+slippage).
FEE_PER_SIDE = 0.0006
SLIPPAGE_PER_SIDE = 0.0003
RISK_FRACTION = 0.005  # illustrative 0.5% paper-account risk per trade
PAPER_EQUITY = 1000.0


def http_json(url, params=None):
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'BitgetSignalMonitor/2.0'})
    with urllib.request.urlopen(req, timeout=18) as response:
        return json.load(response)


def candles(symbol, tf):
    raw = http_json(BASE + '/api/v2/mix/market/candles', {
        'symbol': symbol, 'productType': 'USDT-FUTURES',
        'granularity': tf, 'limit': '350'})
    if raw.get('code') != '00000':
        raise RuntimeError('Bitget: ' + str(raw.get('msg')))
    now = int(time.time() * 1000)
    rows = sorted([(int(x[0]), *[float(v) for v in x[1:6]]) for x in raw['data']])
    rows = [r for r in rows if r[0] + TF_MS[tf] < now - 3000]
    if len(rows) < 215:
        raise RuntimeError(f'{symbol} {tf}: 215 kapali mum bulunamadi')
    if now - rows[-1][0] - TF_MS[tf] > TF_MS[tf] + 120000:
        raise RuntimeError(f'{symbol} {tf}: veri gecikmis')
    return rows


def ema_series(values, period):
    alpha = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(result[-1] + alpha * (v - result[-1]))
    return result


def rsi(values, period=14):
    if len(values) < period + 2:
        return 50.0
    gains = losses = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0)
        losses += max(-delta, 0)
    gains /= period
    losses /= period
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gains = (gains * (period - 1) + max(delta, 0)) / period
        losses = (losses * (period - 1) + max(-delta, 0)) / period
    if losses == 0:
        return 100.0 if gains else 50.0
    return 100 - 100 / (1 + gains / losses)


def atr(rows, period=14):
    tr = [max(rows[i][2] - rows[i][3], abs(rows[i][2] - rows[i - 1][4]),
              abs(rows[i][3] - rows[i - 1][4])) for i in range(1, len(rows))]
    value = sum(tr[:period]) / period
    for v in tr[period:]:
        value = (value * (period - 1) + v) / period
    return value


def classify(rows):
    closes = [r[4] for r in rows]
    e50, e200 = ema_series(closes, 50)[-1], ema_series(closes, 200)[-1]
    if closes[-1] > e50 > e200:
        return 'LONG'
    if closes[-1] < e50 < e200:
        return 'SHORT'
    return 'KARISIK'


def analyze(symbol):
    data = {tf: candles(symbol, tf) for tf in TF_MS}
    trends = {tf: classify(rows) for tf, rows in data.items()}
    five, fifteen = data['5m'], data['15m']
    direction = trends['1H']
    if direction == 'KARISIK' or trends['4H'] != direction or trends['15m'] != direction:
        return None, trends, 'Ana trend uyumsuz'
    if trends['5m'] != direction:
        return None, trends, '5m trend uyumsuz'
    closes = [r[4] for r in five]
    price = closes[-1]
    current_atr = atr(five)
    if current_atr <= 0:
        return None, trends, 'ATR gecersiz'
    atr_pct = current_atr / price
    if not 0.001 <= atr_pct <= 0.014:
        return None, trends, 'Volatilite filtresi'
    recent_vol = [r[5] for r in five[-22:-2]]
    avg_vol = sum(recent_vol) / len(recent_vol)
    vol_ratio = five[-1][5] / avg_vol if avg_vol else 0
    if vol_ratio < 1.35:
        return None, trends, 'Hacim yetersiz'
    momentum = rsi(closes)
    if direction == 'LONG' and not 53 <= momentum <= 73:
        return None, trends, 'RSI filtresi'
    if direction == 'SHORT' and not 27 <= momentum <= 47:
        return None, trends, 'RSI filtresi'
    fast = ema_series(closes, 12)
    slow = ema_series(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    signal_line = ema_series(macd, 9)
    histogram = macd[-1] - signal_line[-1]
    if (direction == 'LONG' and histogram <= 0) or (direction == 'SHORT' and histogram >= 0):
        return None, trends, 'MACD filtresi'
    high20 = max(r[2] for r in five[-21:-1])
    low20 = min(r[3] for r in five[-21:-1])
    if direction == 'LONG' and price <= high20:
        return None, trends, 'Kirilim yok'
    if direction == 'SHORT' and price >= low20:
        return None, trends, 'Kirilim yok'
    # Do not chase a candle too far beyond breakout.
    breakout_level = high20 if direction == 'LONG' else low20
    if abs(price - breakout_level) > 0.8 * current_atr:
        return None, trends, 'Kirilimdan fazla uzak'
    swing = min(r[3] for r in five[-11:]) if direction == 'LONG' else max(r[2] for r in five[-11:])
    if direction == 'LONG':
        stop = min(swing, price - 1.5 * current_atr)
        risk = price - stop
        target = price + 2.2 * risk
    else:
        stop = max(swing, price + 1.5 * current_atr)
        risk = stop - price
        target = price - 2.2 * risk
    if not 0.0015 <= risk / price <= 0.018:
        return None, trends, 'Stop mesafesi uygun degil'
    # A gross 2.2R target is not a guaranteed achievable execution price.
    return {'symbol': symbol, 'direction': direction, 'entry': price, 'stop': stop,
            'target': target, 'atr': current_atr, 'rsi': momentum,
            'volume_ratio': vol_ratio, 'candle': five[-1][0]}, trends, 'ADAY'


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def notify(cfg, message):
    token, chat_id = str(cfg.get('token', '')).strip(), str(cfg.get('chat_id', '')).strip()
    if not token or not chat_id:
        print('Telegram ayarlari eksik; bildirim gonderilemedi')
        return False
    data = http_json('https://api.telegram.org/bot' + token + '/sendMessage',
                     {'chat_id': chat_id, 'text': message})
    if not data.get('ok'):
        raise RuntimeError('Telegram API: ' + str(data.get('description', 'hata')))
    return True


def record(event):
    with TRADES.open('a', encoding='utf-8') as out:
        out.write(json.dumps(event, ensure_ascii=False) + '\n')


def manage_paper(state, symbol, rows):
    pos = state['open'].get(symbol)
    if not pos:
        return None
    # Evaluate only bars strictly after the signal candle; conservative stop-first.
    newer = [r for r in rows if r[0] > pos['candle']]
    if not newer:
        return None
    direction = pos['direction']
    outcome = None
    exit_price = None
    for r in newer:
        hit_stop = r[3] <= pos['stop'] if direction == 'LONG' else r[2] >= pos['stop']
        hit_target = r[2] >= pos['target'] if direction == 'LONG' else r[3] <= pos['target']
        if hit_stop:
            outcome, exit_price = 'STOP', pos['stop']
            break
        if hit_target:
            outcome, exit_price = 'HEDEF', pos['target']
            break
    if not outcome and newer[-1][0] - pos['candle'] >= 48 * TF_MS['5m']:
        outcome, exit_price = 'SURE_DOLDU', newer[-1][4]
    if not outcome:
        return None
    sign = 1 if direction == 'LONG' else -1
    qty = pos['risk_usdt'] / abs(pos['entry'] - pos['stop'])
    gross = (exit_price - pos['entry']) * sign * qty
    fees = qty * (pos['entry'] + exit_price) * (FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
    pnl = gross - fees
    event = {'event': 'CLOSE', 'symbol': symbol, 'direction': direction,
             'outcome': outcome, 'entry': pos['entry'], 'exit': exit_price,
             'net_pnl_usdt': round(pnl, 4), 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    record(event)
    del state['open'][symbol]
    state['equity'] = round(state['equity'] + pnl, 4)
    return event


# =============================================================================
# v3 / BTC EMA shadow A/B: experimental paper forward tracking, read-only API.
# Independently compares EMA50/200 vs EMA20/50/200, strictly no live orders.
# =============================================================================
AB_VERSION = '3.0'
AB_STATE_FILE = ROOT / 'bitget_v3_ab_durum.json'
AB_LOG = ROOT / 'bitget_v3_ab_islemler.jsonl'
AB_REPORT = ROOT / 'bitget_v3_ab_rapor.txt'
AB_METHODS = ('EMA_50_200', 'EMA_20_50_200')
AB_EQUITY = 1000.0  # a SEPARATE virtual account for each strategy
AB_FEE = 0.0006      # estimate, not necessarily user's account fee
AB_SLIP = 0.0003     # conservative illustrative slippage on every execution
AB_RISK = 0.005      # maximum estimated stop risk as share of virtual account
AB_TIMEOUT_4H = 36  # 36 * 4h = 6 days
AB_MAX_SIGNAL_LAG_MS = 20 * 60_000


def ab_utc(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def ab_default_state():
    return {
        'version': 3, 'primed_4h': None, 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'accounts': {method: {'cash': AB_EQUITY, 'position': None, 'closed': 0,
                              'wins': 0, 'losses': 0, 'invalid': 0, 'funding_approx_usdt': 0.0,
                              'fees_and_slip_estimated': True} for method in AB_METHODS},
        'last_report_week': None,
    }


def ab_validate_state(state):
    if state.get('version') != 3 or set(state.get('accounts', {})) != set(AB_METHODS):
        raise ValueError('v3 sanal takip durum dosyasi uyumsuz. Veri silinmedi, islem durduruldu.')
    for acc in state['accounts'].values():
        if not isinstance(acc.get('cash'), (float, int)) or acc['cash'] < 0:
            raise ValueError('v3 sanal bakiye gecersiz. Islem durduruldu.')
    return state


def ab_get_4h(symbol='BTCUSDT'):
    # Official v2 public market-candle endpoint: up to 1000 bars. Only closed bars.
    raw = http_json(BASE + '/api/v2/mix/market/candles', {
        'symbol': symbol, 'productType': 'USDT-FUTURES', 'granularity': '4H', 'limit': '1000'})
    if raw.get('code') != '00000' or not isinstance(raw.get('data'), list):
        raise RuntimeError('Bitget 4H veri hatasi: ' + str(raw.get('msg')))
    now = int(time.time() * 1000)
    bars = sorted([(int(r[0]), *[float(v) for v in r[1:6]]) for r in raw['data']])
    bars = [r for r in bars if r[0] + TF_MS['4H'] < now - 3000]
    if len(bars) < 450:
        raise RuntimeError(f'4H icin 450 kapanmis mum gerekli, alinan: {len(bars)}')
    for prev, curr in zip(bars, bars[1:]):
        if curr[0] - prev[0] != TF_MS['4H']:
            raise RuntimeError('4H mumlarda bosluk veya tekrar var. Islem yok.')
    if now - (bars[-1][0] + TF_MS['4H']) > TF_MS['4H'] + 120000:
        raise RuntimeError('Bitget 4H veri gecikmis. Islem yok.')
    return bars


def ab_atr_4h(rows):
    return atr(rows, period=14)


def ab_signals(rows):
    closes = [r[4] for r in rows]
    e20, e50, e200 = (ema_series(closes, n) for n in (20, 50, 200))
    signals = {}
    for method in AB_METHODS:
        trend = []
        for i in range(len(closes)):
            if i < 260:
                trend.append(0)
            elif method == 'EMA_50_200':
                trend.append(1 if closes[i] > e200[i] and e50[i] > e200[i]
                             else -1 if closes[i] < e200[i] and e50[i] < e200[i] else 0)
            else:
                trend.append(1 if closes[i] > e200[i] and e20[i] > e50[i]
                             else -1 if closes[i] < e200[i] and e20[i] < e50[i] else 0)
        signals[method] = (trend[-2], trend[-1])
    return signals


def ab_funding_records(symbol='BTCUSDT'):
    # Public Bitget v3 history funding (not forecast funding). Retrieve 3 pages
    # to handle symbols that settle hourly while a position is open for 6 days.
    found = {}
    for page in (1, 2, 3):
        raw = http_json(BASE + '/api/v3/market/history-fund-rate', {
            'category': 'USDT-FUTURES', 'symbol': symbol,
            'limit': '100', 'cursor': str(page)})
        if raw.get('code') != '00000':
            raise RuntimeError('Funding API hatasi: ' + str(raw.get('msg')))
        items = raw.get('data', {}).get('resultList', [])
        if not isinstance(items, list):
            raise RuntimeError('Funding API yanit bicimi taninmiyor')
        for x in items:
            t, rate = int(x['fundingRateTimestamp']), float(x['fundingRate'])
            if not math.isfinite(rate):
                raise ValueError('Funding rate finite degil')
            found[t] = rate
        if len(items) < 100:
            break
    if not found:
        raise RuntimeError('Funding kayitlari bos geldi; sanal takip bu tur bekleyecek')
    return sorted(found.items())


def ab_record(event):
    with AB_LOG.open('a', encoding='utf-8') as out:
        out.write(json.dumps(event, ensure_ascii=False) + '\n')


def ab_label(method):
    return 'A / EMA 50-200' if method == 'EMA_50_200' else 'B / EMA 20-50-200'


def ab_entry(account, method, direction, reference, atr4h, signal_bar_ms, five_bar_ms):
    if account['position'] is not None or not (atr4h > 0 and reference > 0):
        return None
    if account['cash'] < 10:
        return None
    entry = reference * (1 + direction * AB_SLIP)
    distance = 2 * atr4h
    # Risk budget includes exit fee and both price slips (approximated conservatively).
    fee_slip_budget = (AB_FEE + AB_SLIP) * 2 * entry
    qty = min(account['cash'] / (entry * (1 + AB_FEE)),
              account['cash'] * AB_RISK / (distance + fee_slip_budget))
    if qty <= 0:
        return None
    fee = entry * qty * AB_FEE
    account['cash'] -= fee
    p = {
        'direction': direction, 'entry': entry, 'qty': qty,
        'stop': entry - direction * distance, 'target': entry + direction * 2 * distance,
        'entry_fee': fee, 'entry_atr': atr4h,
        'entry_4h_bar': signal_bar_ms, 'entry_5m_bar': five_bar_ms,
        'last_processed_5m': five_bar_ms, 'last_funding_ms': five_bar_ms,
        'funding_approx': 0.0, 'funding_incomplete': False, 'opened_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    account['position'] = p
    event = {'event': 'OPEN', 'model': method, 'market': 'BTCUSDT',
             'timestamp_utc': dt.datetime.now(dt.timezone.utc).isoformat(), **p}
    ab_record(event)
    return (f'SANAL A/B {ab_label(method)} GIRIS\n'
            f"BTCUSDT {'LONG' if direction > 0 else 'SHORT'}\n"
            f'Giris tahmini: {entry:.2f} | Stop: {p["stop"]:.2f} | Hedef: {p["target"]:.2f}\n'
            f'Hacim: {qty:.6f} BTC | Ayrı sanal bakiye: {account["cash"]:.2f} USDT\n'
            'Sadece sanal takip. Gercek emir verilmedi.')


def ab_exit(account, method, reference, reason, candle_ms, valid=True):
    p = account['position']
    if p is None:
        return None
    direction = p['direction']
    # Slippage is adverse on exit; a stop gapped beyond uses worst available open.
    exit_price = reference * (1 - direction * AB_SLIP)
    exit_fee = exit_price * p['qty'] * AB_FEE
    realized = direction * (exit_price - p['entry']) * p['qty'] - exit_fee
    account['cash'] += realized
    total_pnl = realized - p['entry_fee'] + p['funding_approx']
    valid = valid and not p.get('funding_incomplete', False)
    account['position'] = None
    if valid:
        account['closed'] += 1
        account['wins' if total_pnl > 0 else 'losses'] += 1
    else:
        account['invalid'] += 1
    event = {
        'event': 'CLOSE' if valid else 'INVALID_GAP', 'model': method,
        'timestamp_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'candle_ms': candle_ms, 'reason': reason, 'side': direction,
        'entry': p['entry'], 'exit': exit_price, 'qty': p['qty'],
        'net_pnl_approx': round(total_pnl, 4),
        'funding_approx': round(p['funding_approx'], 4),
        'cash_after': round(account['cash'], 4), 'valid_for_comparison': valid,
    }
    ab_record(event)
    if not valid:
        return (f'SANAL A/B VERI BOSLUGU: {ab_label(method)}\n'
                'Fiyat takibi kesildigi icin islem KARSILASTIRMADAN HARIC tutuldu.\n'
                f'Kapatma referansi: {exit_price:.2f} USDT. Gercek emir yok.')
    return (f'SANAL A/B {ab_label(method)} KAPANIS ({reason})\n'
            f'Yaklasik net PnL: {total_pnl:+.2f} USDT\n'
            f'Sanal bakiye: {account["cash"]:.2f} USDT\n'
            'Komisyon, kayma ve yaklasik funding dahil; emir gerceklesmesi varsayimsal.')


def ab_process_5m(account, method, five, funding_records):
    pos = account['position']
    if not pos:
        return []
    newer = [r for r in five if r[0] > pos['last_processed_5m']]
    if not newer:
        return []
    expected = pos['last_processed_5m'] + TF_MS['5m']
    messages = []
    for bar in newer:
        t, opened, high, low, close, _ = bar
        if t != expected:
            m = ab_exit(account, method, opened, 'VERI_BOSLUGU', t, valid=False)
            if m:
                messages.append(m)
            return messages
        expected += TF_MS['5m']
        # Settle only funding events known to have occurred by the bar OPEN.
        # Do it BEFORE possible intrabar stop/target exit; never after exit.
        ab_apply_funding(account, funding_records, five, t)
        pos['last_processed_5m'] = t
        side = pos['direction']
        hit_stop = low <= pos['stop'] if side > 0 else high >= pos['stop']
        hit_target = high >= pos['target'] if side > 0 else low <= pos['target']
        if hit_stop:
            raw = min(opened, pos['stop']) if side > 0 else max(opened, pos['stop'])
            m = ab_exit(account, method, raw, 'STOP' if not hit_target else 'STOP_ONCELIKLI', t)
            if m:
                messages.append(m)
            return messages
        if hit_target:
            m = ab_exit(account, method, pos['target'], 'HEDEF', t)
            if m:
                messages.append(m)
            return messages
    return messages


def ab_apply_funding(account, funding_records, five, through_ms):
    pos = account['position']
    if not pos or funding_records is None:
        return
    # Official Bitget funding rates; mark price at settlement is approximated by
    # last completed 5m market candle. Future candles must never be used.
    for ts, rate in funding_records:
        if ts <= pos['last_funding_ms'] or ts > through_ms:
            continue
        before = [r for r in five if r[0] + TF_MS['5m'] <= ts]
        if not before:
            # We lack the historical close for an exact candle-matched proxy.
            # Flag as incomplete rather than silently charging zero.
            pos['funding_incomplete'] = True
            pos['last_funding_ms'] = ts
            continue
        proxy = before[-1][4]
        paid = -pos['direction'] * rate * pos['qty'] * proxy
        account['cash'] += paid
        pos['funding_approx'] += paid
        account['funding_approx_usdt'] += paid
        pos['last_funding_ms'] = ts


def ab_report(state):
    lines = [
        'BITGET BTCUSDT | A/B SANAL ILERI TEST v3',
        'Modeller 4H kapanmis mum sinyalleriyle izlenir; 5 dk aralikla kontrol edilir.',
        'Her stratejinin baslangic sanal bakiyesi 1000 USDT; birbirinden bagimsiz.',
        'Gercek emir yok. Varsayimlar: %0.06 taker + %0.03 kayma (her yon),',
        'islem basina yaklasik %0.5 risk, maksimum 1x pozisyon, stop 2 ATR, hedef 4 ATR.',
        'Funding: Bitget resmi tarihsel oran; kapanmis 5m fiyat ile YAKLASIK mark degeri.',
        'Bu ileri test borsada gerceklesen islem degildir. Fiyat kaymasi ve',
        'likidasyon farklari olabilir. Yuzdeler gelecek kazanc vaadi degildir.',
        f'Test baslangici (UTC): {state["started_utc"]}',
        f'Rapor (UTC): {dt.datetime.now(dt.timezone.utc).isoformat()}', '',
    ]
    for method in AB_METHODS:
        x = state['accounts'][method]
        change = (x['cash'] / AB_EQUITY - 1) * 100
        lines += [f'{ab_label(method)}:',
                  f'   Gerceklesen sanal bakiye: {x["cash"]:.2f} USDT ({change:+.2f}%)',
                  f'   Kapanan islem: {x["closed"]} | Kazanc: {x["wins"]} | Zarar: {x["losses"]}',
                  f'   Gecersiz/veri boslugu: {x["invalid"]}' + (' | KARSILASTIRMA GECERSIZ' if x['invalid'] else ''),
                  f'   Yaklasik funding net toplam: {x["funding_approx_usdt"]:+.3f} USDT',
                  f'   Acik islem: {"VAR" if x["position"] else "YOK"}', '']
    lines += ['Not: Acik pozisyonlarin piyasa degeri, gerceklesmis nakit bakiyeye dahil degildir.',
              'Sonuclar karar vermek icin yeterli islem sayisina ulasana dek aday durumundadir.']
    tmp = AB_REPORT.with_suffix('.tmp')
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    tmp.replace(AB_REPORT)


def ab_tick(state, five, four, funding_records=None):
    """Pure-ish orchestration: returns outgoing notification texts; never places orders."""
    signal_ms = four[-1][0]
    last = state['primed_4h']
    messages = []
    if last is None:
        state['primed_4h'] = signal_ms
        return ['Bitget A/B sanal takip basladi: BTC 4H EMA 50/200 ve EMA 20/50/200. '
                'Baslangicta gecmise donuk islem acilmadi; yalniz yeni sinyaller izlenecek.']
    for method in AB_METHODS:
        acc = state['accounts'][method]
        # Process completed 5min bars first to avoid peek-ahead.
        messages += ab_process_5m(acc, method, five, funding_records)
    if signal_ms <= last:
        return messages
    state['primed_4h'] = signal_ms
    if (int(time.time() * 1000) - signal_ms - TF_MS['4H']) > AB_MAX_SIGNAL_LAG_MS:
        return messages + ['BTC 4H kapanisi gec fark edildi: yeni sanal islem ACILMADI (stale signal).']
    sigs = ab_signals(four)
    a4h = ab_atr_4h(four)
    ref_price = five[-1][4]
    five_ms = five[-1][0]
    for method in AB_METHODS:
        acc = state['accounts'][method]
        old, new = sigs[method]
        p = acc['position']
        if p and (new != p['direction'] or signal_ms - p['entry_4h_bar'] >= AB_TIMEOUT_4H * TF_MS['4H']):
            m = ab_exit(acc, method, ref_price, 'TREND_DEGISIMI_VEYA_SURE', five_ms)
            if m:
                messages.append(m)
        if acc['position'] is None and old != new and new:
            m = ab_entry(acc, method, new, ref_price, a4h, signal_ms, five_ms)
            if m:
                messages.append(m)
    return messages


def ab_weekly_summary(state):
    # One weekly summary on Sunday (the first tick of that day, local time).
    local = dt.datetime.now()
    week_key = local.strftime('%G-W%V')
    if local.weekday() != 6 or state['last_report_week'] == week_key:
        return None
    state['last_report_week'] = week_key
    lines = ['BITGET A/B HAFTALIK SANAL RAPOR (BTC)']
    for method in AB_METHODS:
        acc = state['accounts'][method]
        v = (acc['cash'] / AB_EQUITY - 1) * 100
        lines.append(f'{ab_label(method)}: {acc["cash"]:.2f} USDT ({v:+.2f}%), '
                     f'{acc["closed"]} kapanan islem (K {acc["wins"]}/Z {acc["losses"]})')
    lines.append('Yalniz sanal tahmini sonuclar. Ayrintili dosya: bitget_v3_ab_rapor.txt')
    return '\n'.join(lines)


def ab_run_cycle(state, cfg):
    # Failure in A/B logic does NOT affect existing v2 signal monitor.
    four = ab_get_4h('BTCUSDT')
    five = candles('BTCUSDT', '5m')
    need_funding = any(state['accounts'][x]['position'] for x in AB_METHODS)
    fr = None
    if need_funding:
        # Fail closed. Missing funding must not be treated as free holding.
        fr = ab_funding_records('BTCUSDT')
    messages = ab_tick(state, five, four, fr)
    week = ab_weekly_summary(state)
    if week:
        messages.append(week)
    # Save state AND report before external notifications, prevents duplicate entries.
    save_json(AB_STATE_FILE, state)
    ab_report(state)
    for msg in messages:
        try:
            notify(cfg, msg)
        except Exception as exc:
            print('A/B Telegram bildirimi gonderilemedi:', str(exc), flush=True)
    print('A/B BTC', ' | '.join(f'{ab_label(m)}={state["accounts"][m]["cash"]:.2f}'
                                for m in AB_METHODS), flush=True)


def main():
    print('BITGET SINYAL TAKIP v3 | v2 SINYALLER + BTC A/B SANAL TEST | GERCEK EMIR YOK')
    cfg = load_json(CONFIG, {})
    if not cfg.get('token') or not cfg.get('chat_id'):
        print('Telegram ayari eksik. Once eski surumde ayarlari tamamlayin.')
        return
    state = load_json(STATE, {'open': {}, 'last_signal': {}, 'equity': PAPER_EQUITY})
    ab_state = ab_validate_state(load_json(AB_STATE_FILE, ab_default_state()))
    if 'open' not in state or 'last_signal' not in state:
        raise ValueError('Durum dosyasi bozuk')
    try:
        notify(cfg, 'Bitget Sinyal Takip v2 baslatildi. BTC/ETH, 5 dakikada bir.\n'
                    'Yalnizca guclu aday sinyaller + sanal islem. GERCEK EMIR YOK.')
        print('Telegram baslangic mesaji gonderildi.')
    except Exception as exc:
        print('Telegram baglanti hatasi:', exc)
    while True:
        now_str = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            ab_run_cycle(ab_state, cfg)
        except Exception as ab_exc:
            print(now_str, 'A/B TAKIP HATASI:', type(ab_exc).__name__, str(ab_exc), flush=True)
        for symbol in SYMBOLS:
            try:
                five = candles(symbol, '5m')
                event = manage_paper(state, symbol, five)
                if event:
                    save_json(STATE, state)
                    notify(cfg, f"SANAL ISLEM KAPANDI {symbol} {event['outcome']}\n"
                                f"Net PnL (tahmini): {event['net_pnl_usdt']:+.2f} USDT\n"
                                f"Sanal bakiye: {state['equity']:.2f} USDT")
                if symbol in state['open']:
                    print(now_str, symbol, 'Sanal pozisyon acik, yeni sinyal yok', flush=True)
                    continue
                candidate, trends, reason = analyze(symbol)
                print(now_str, symbol, trends, reason, flush=True)
                if not candidate:
                    continue
                key = f"{candidate['direction']}:{candidate['candle']}"
                if state['last_signal'].get(symbol) == key:
                    continue
                risk_budget = max(0.0, state['equity']) * RISK_FRACTION
                if risk_budget <= 0:
                    print('Sanal bakiye tukenmis; sinyal atlandi')
                    continue
                candidate['risk_usdt'] = risk_budget
                msg = (f"BITGET v2 {symbol} {candidate['direction']} - ADAY SINYAL\n"
                       f"Kapanmis 5m giris referansi: {candidate['entry']:.2f} USDT\n"
                       f"Stop: {candidate['stop']:.2f}\n"
                       f"2.2R hedef: {candidate['target']:.2f}\n"
                       f"RSI: {candidate['rsi']:.1f} | Hacim: {candidate['volume_ratio']:.2f}x\n"
                       f"Trend 5m/15m/1H/4H: {trends}\n"
                       f"Sanal risk: {risk_budget:.2f} USDT (%0.5)\n"
                       'Uyari: fiyat kaymasi, komisyon, funding ve likidasyon riski vardir. '
                       'Garanti degildir. Gercek emir acilmaz.')
                # Persist before sending to avoid duplicate alert after a network timeout.
                state['last_signal'][symbol] = key
                state['open'][symbol] = candidate
                save_json(STATE, state)
                record({'event': 'OPEN', **candidate,
                        'time_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
                try:
                    notify(cfg, msg)
                except Exception as exc:
                    print('Telegram bildirimi basarisiz; tekrar icin manuel kontrol gerekli:', exc)
            except Exception as exc:
                print(now_str, symbol, 'HATA:', type(exc).__name__, str(exc), flush=True)
        save_json(STATE, state)
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nBot durduruldu.')