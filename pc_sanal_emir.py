# -*- coding: utf-8 -*-
"""Bitget public BTC/ETH quotes: two strictly separated paper-only experiments.

A) One TECHNICAL SYSTEM TEST each for BTC and ETH: a real current Bitget
   ticker price is used to simulate an entry and a 90-second exit, irrespective
   of any strategy. Its profit/loss NEVER enters strategy performance.
B) After that, a 5m EMA21 close-cross operational DEMO strategy can open
   LONG or SHORT paper positions only at NEW, actually closed market candles.

No private API keys, no order endpoints, no live exchange account balances.
Strategies are NOT validated profitable; expenses are simulated.
"""
import datetime as dt
import json
import math
import time
from pathlib import Path

import bitget_sinyal_takip as engine

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'pc_sanal_emir_durum.json'
EVENTS = ROOT / 'pc_sanal_emirler.jsonl'
REPORT = ROOT / 'pc_sanal_sonuc.txt'
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
INITIAL_EQUITY = 1000.0
FIVE = 300_000
FEE_SIDE = 0.0006  # assumed Bitget market-order commission
SLIP_SIDE = 0.0003  # adverse hypothetical execution price movement
RISK_SHARE = 0.005
NOTIONAL_CAP = 1.0
MAX_QUOTE_AGE = 15_000
MAX_QUOTE_GAP = 90_000
INITIAL_TEST_HOLD = 90_000
STRATEGY_MAX_HOLD = 4 * 3_600_000
STRATEGY_NAME = 'EMA21_5M_DEMO_NOT_VALIDATED'


def utc(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def new_account(now_ms):
    return {
        'balance': INITIAL_EQUITY,
        'peak': INITIAL_EQUITY,
        'max_drawdown_pct': 0.0,
        'closed': 0,
        'wins': 0,
        'losses': 0,
        'test_done': False,
        'test_pnl': None,
        'open': None,
        'last_quote_ms': 0,
        'last_5m': ((now_ms - 5000) // FIVE - 1) * FIVE,
        'next_id': 1,
        'unverified_aborts': 0,
    }


def new_state(now_ms):
    return {
        'version': 1,
        'created_utc': utc(now_ms),
        'accounts': {symbol: new_account(now_ms) for symbol in SYMBOLS},
    }


class PaperBook:
    def __init__(self, now_ms=None, state_file=STATE, events_file=EVENTS,
                 report_file=REPORT):
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        self.state_file = Path(state_file)
        self.events_file = Path(events_file)
        self.report_file = Path(report_file)
        if self.state_file.exists():
            self.state = engine.load_json(self.state_file, {})
            if self.state.get('version') != 1:
                raise RuntimeError('Sanal defter versiyonu uyumsuz; eski kayit silinmedi')
            if set(self.state.get('accounts', {})) != set(SYMBOLS):
                raise RuntimeError('Sanal hesap yapisi uyumsuz')
            # We have no reliable ticks while the PC was off; NEVER silently
            # declare a missed position profitable or losing. Abandon as UNKNOWN.
            for sym in SYMBOLS:
                acc = self.state['accounts'][sym]
                p = acc.get('open')
                if p:
                    self.event({
                        'event': 'UNVERIFIED_RESTART', 'symbol': sym,
                        'trade_id': p['id'], 'kind': p['kind'],
                        'time_utc': utc(now_ms),
                        'reason': 'PC offline: intrabar fill sequence unknown',
                        'pnl_usdt': None
                    })
                    acc['unverified_aborts'] += 1
                    acc['open'] = None
                    if p['kind'] == 'SYSTEM_TEST':
                        acc['test_done'] = True
                    # No PnL credited, no closed-strategy trade counted.
                acc['last_quote_ms'] = 0
        else:
            self.state = new_state(now_ms)
        self.persist()

    def persist(self):
        engine.save_json(self.state_file, self.state)
        self.write_report()

    def event(self, item):
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        with self.events_file.open('a', encoding='utf-8') as f:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

    def write_report(self):
        lines = [
            'BITGET - PC OTOMATIK SANAL EMIR RAPORU',
            'Gercek borsa emri: YOK. Bu dosya yerel simulasyondur.',
            'Her sembol icin ayri baslangic: 1000 USDT.',
            'Sistem test islemi strateji kazanma istatistiklerine DAHIL DEGIL.',
            '5m EMA21 stratejisi: DENEYSEL, karliligi kanitlanmadi.',
            'Model: %0.06 komisyon ve %0.03 fiyat kaymasi HER TARAFTA.',
            'Funding, gercek spread ve orderbook dolumlari yoktur.',
            ''
        ]
        for sym in SYMBOLS:
            acc = self.state['accounts'][sym]
            p = acc['open']
            lines.extend([
                f'{sym}',
                f'  Strateji sanal bakiye: {acc["balance"]:.3f} USDT',
                f'  Strateji net PnL: {acc["balance"]-INITIAL_EQUITY:+.3f} USDT',
                f'  Strateji kapanan: {acc["closed"]}, kazanan: {acc["wins"]}, kaybeden: {acc["losses"]}',
                '  Teknik test: ' + ('tamamlandi' if acc['test_done'] else 'bekliyor'),
                '  Teknik test PnL: ' + (f'{acc["test_pnl"]:+.3f} USDT' if acc['test_pnl'] is not None else 'henüz yok'),
                f'  Veri boslugu / yeniden baslama sonucu belirsiz: {acc["unverified_aborts"]}',
                ('  ACIK SANAL: ' + f'{p["kind"]} {"LONG" if p["direction"]==1 else "SHORT"} '
                 + f'giris={p["entry"]:.2f}, stop={p["stop"]}, hedef={p["target"]}'
                 if p else '  Acik sanal pozisyon: YOK'),
                ''
            ])
        self.report_file.write_text('\n'.join(lines), encoding='utf-8')

    def status(self):
        parts = []
        for sym in SYMBOLS:
            a = self.state['accounts'][sym]
            p = a['open']
            label = 'TEST' if p and p['kind']=='SYSTEM_TEST' else 'STRATEJI' if p else 'BOS'
            parts.append(f'{sym[:3]} {label}: {a["closed"]} kapanan, '
                         f'{a["balance"]-INITIAL_EQUITY:+.2f} USDT')
        return ' | '.join(parts)

    def _open(self, sym, kind, direction, raw_price, now_ms, stop=None, target=None):
        account = self.state['accounts'][sym]
        if account['open']:
            return None
        entry = raw_price * (1 + direction * SLIP_SIDE)
        if kind == 'SYSTEM_TEST':
            qty = 100.0 / entry  # $100 simulated notional, separate from account
            deadline = now_ms + INITIAL_TEST_HOLD
        else:
            risk_per_unit = (entry - stop) * direction
            if risk_per_unit <= 0 or (target - entry) * direction <= 0:
                return None
            qty = min(account['balance'] * RISK_SHARE / risk_per_unit,
                      account['balance'] * NOTIONAL_CAP / entry)
            deadline = now_ms + STRATEGY_MAX_HOLD
        if qty <= 0:
            return None
        trade_id = f'{sym}-{account["next_id"]:04d}'
        account['next_id'] += 1
        account['open'] = {
            'id': trade_id, 'kind': kind, 'direction': direction,
            'entry': entry, 'qty': qty, 'stop': stop, 'target': target,
            'opened_ms': now_ms, 'deadline_ms': deadline
        }
        self.persist()
        self.event({
            'event': 'OPEN', 'trade_id': trade_id, 'kind': kind, 'symbol': sym,
            'direction': 'LONG' if direction == 1 else 'SHORT',
            'time_utc': utc(now_ms), 'entry': entry, 'qty': qty,
            'notional_usdt': round(entry * qty, 4),
            'stop': stop, 'target': target,
            'fee_per_side': FEE_SIDE, 'slippage_per_side': SLIP_SIDE
        })
        label = 'TEKNIK SISTEM TESTI (SINYAL DEGIL)' if kind=='SYSTEM_TEST' else '5DK EMA21 STRATEJI DENEMESI'
        return (f'{sym} | SANAL EMIR ACILDI | {label}\n'
                f'{"LONG" if direction==1 else "SHORT"} | Giris: {entry:,.2f} USDT\n'
                f'Nominal: {qty*entry:.2f} USDT'
                + (f'\nStop: {stop:,.2f} | Hedef: {target:,.2f}' if stop is not None else
                   '\n90 saniye sonra mevcut fiyatla test kapatilacak.')
                + '\nGERCEK EMIR YOK. Kar garantisi yok.')

    def _close(self, sym, raw_price, now_ms, reason):
        account = self.state['accounts'][sym]
        trade = account['open']
        if not trade:
            return None
        direction = trade['direction']
        exit_price = raw_price * (1-direction*SLIP_SIDE)
        qty = trade['qty']
        gross = direction * (exit_price - trade['entry']) * qty
        fee = FEE_SIDE * qty * (exit_price + trade['entry'])
        pnl = gross-fee
        if trade['kind'] == 'SYSTEM_TEST':
            account['test_done'] = True
            account['test_pnl'] = round(pnl, 6)
        else:
            account['balance'] += pnl
            account['closed'] += 1
            account['wins' if pnl > 0 else 'losses'] += 1
            account['peak'] = max(account['balance'], account['peak'])
            account['max_drawdown_pct'] = min(
                account['max_drawdown_pct'],
                100 * (account['balance'] / account['peak']-1))
        account['open'] = None
        self.persist()
        self.event({
            'event': 'CLOSE', 'trade_id': trade['id'], 'kind': trade['kind'],
            'symbol': sym, 'direction': 'LONG' if direction==1 else 'SHORT',
            'reason': reason, 'opened_utc': utc(trade['opened_ms']),
            'closed_utc': utc(now_ms), 'entry': trade['entry'], 'exit': exit_price,
            'qty': qty, 'gross_pnl_usdt': round(gross, 6),
            'fee_usdt': round(fee, 6), 'net_pnl_usdt': round(pnl, 6),
            'strategy_balance_usdt': round(account['balance'], 6)
        })
        tag = 'TEKNIK TEST KAPANDI (STRATEJI KARI DEGIL)' if trade['kind']=='SYSTEM_TEST' else '5DK STRATEJI SANAL EMIR KAPANDI'
        return (f'{sym} | {tag}\n'
                f'Sebep: {reason} | {"LONG" if direction==1 else "SHORT"}\n'
                f'Giris {trade["entry"]:,.2f} -> Cikis {exit_price:,.2f} USDT\n'
                f'Komisyon: {fee:.3f} USDT | NET: {pnl:+.3f} USDT\n'
                f'Strateji bakiye: {account["balance"]:.2f} USDT\n'
                'GERCEK EMIR YOK.')

    def on_quote(self, sym, price, quote_ms, now_ms=None):
        """At most once per fresh incoming ticker. No trade using stale prices."""
        if now_ms is None:
            now_ms = int(time.time()*1000)
        if sym not in SYMBOLS or not math.isfinite(price) or price <= 0:
            return []
        if not (0 <= now_ms-quote_ms <= MAX_QUOTE_AGE):
            return []
        a = self.state['accounts'][sym]
        last = a['last_quote_ms']
        if quote_ms <= last:
            return []
        messages = []
        if a['open'] and last and quote_ms-last > MAX_QUOTE_GAP:
            old=a['open']
            self.event({'event': 'UNKNOWN_EXIT', 'trade_id': old['id'], 'symbol':sym,
                        'kind':old['kind'], 'time_utc':utc(now_ms), 'pnl_usdt':None,
                        'reason':'Ticker blackout over 90 seconds: stop/target cannot be verified'})
            a['unverified_aborts'] += 1
            if old['kind']=='SYSTEM_TEST':
                a['test_done'] = True
            a['open']=None
            messages.append(
                f'{sym} SANAL TAKIP VERI BOSLUGU: Onceki islem sonucunu '
                'dogrulayamadik; kar/zarar sayilmadi. GERCEK EMIR YOK.')
        a['last_quote_ms'] = quote_ms
        trade = a['open']
        if trade:
            direction=trade['direction']
            if trade['kind'] == 'SYSTEM_TEST':
                if now_ms >= trade['deadline_ms']:
                    messages.append(self._close(sym,price,now_ms,'90_SN_SISTEM_TESTI'))
            else:
                if ((direction==1 and price<=trade['stop']) or
                    (direction==-1 and price>=trade['stop'])):
                    messages.append(self._close(sym,price,now_ms,'STOP'))
                elif ((direction==1 and price>=trade['target']) or
                      (direction==-1 and price<=trade['target'])):
                    messages.append(self._close(sym,price,now_ms,'HEDEF'))
                elif now_ms >= trade['deadline_ms']:
                    messages.append(self._close(sym,price,now_ms,'4_SAAT_SURE'))
        elif not a['test_done']:
            # Deliberately not a strategy trade! Test the whole end-to-end
            # opening/closing/log/Telegram pathway with a genuine live ticker.
            direction=1 if sym=='BTCUSDT' else -1
            msg=self._open(sym,'SYSTEM_TEST',direction,price,now_ms)
            if msg:
                messages.append(msg)
        if messages and a['open'] is None:
            self.persist()
        return messages

    def on_closed_5m(self, sym, rows, price, quote_ms, now_ms):
        """New 5m EMA21 close-cross, no lookahead. Pure operational demo."""
        if sym not in SYMBOLS:
            return []
        a=self.state['accounts'][sym]
        candle_open=((now_ms-5000)//FIVE-1)*FIVE
        if candle_open<=a['last_5m']:
            return []
        if now_ms-(candle_open+FIVE)>90_000:
            a['last_5m']=candle_open
            self.persist()
            return []
        if not rows or rows[-1][0]!=candle_open or len(rows)<50:
            return []
        # Mark this 5m candle as processed even if currently in a position.
        a['last_5m']=candle_open
        self.persist()
        if not a['test_done'] or a['open']:
            return []
        if price is None or quote_ms is None or not math.isfinite(price) or price<=0:
            return []
        if not 0<=now_ms-quote_ms<=MAX_QUOTE_AGE:
            return []
        closes=[r[4] for r in rows]
        ema21=engine.ema_series(closes,21)
        previous=closes[-2]-ema21[-2]
        current=closes[-1]-ema21[-1]
        direction=(1 if previous<=0 and current>0 else
                   -1 if previous>=0 and current<0 else 0)
        if direction==0:
            return []
        atr=engine.atr(rows)
        if atr<=0:
            return []
        # Do not enter after a big price jump between candle close and live ticker.
        if abs(price-closes[-1])>atr*.75:
            return []
        stop_distance=max(1.5*atr,price*.0025)
        stop=price-direction*stop_distance
        target=price+direction*2*stop_distance
        msg=self._open(sym,STRATEGY_NAME,direction,price,now_ms,stop,target)
        return [msg] if msg else []
