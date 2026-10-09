# -*- coding: utf-8 -*-
"""ETHUSDT 1H Donchian-20 forward-paper experiment. NEVER sends orders.

A separate 1,000-USDT hypothetical account. Uses unchanged rules from
research_alternatives.py (H1_CHANNEL20). Tracks closed 5m candles including
entry candle, with conservative stop-first exits. Trading costs estimated.
When market data is missing, the experiment is SUSPENDED, not marked a winner.
"""
import bisect
import datetime as dt
import json
import math
import time
from pathlib import Path

import bitget_sinyal_takip as engine
import research_alternatives as rules

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'pc_eth_forward_state.json'
HISTORY = ROOT / 'pc_eth_forward_trades.jsonl'
FIVE = 300_000
HOUR = 3_600_000
FOUR = 14_400_000
START_EQUITY = 1000.0
FEE = 0.0006
SLIP = 0.0003
MAX_RISK = 0.005
MAX_NOTIONAL = 1.0
MAX_SIGNAL_DELAY_MS = 90_000
QUOTE_MAX_AGE_MS = 30_000
MAX_ENTRY_DRIFT_ATR = 0.5
MODEL = 'H1_CHANNEL20'


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()


def default_state(now_ms):
    return {
        'version': 1,
        'method': MODEL,
        'symbol': 'ETHUSDT',
        'equity': START_EQUITY,
        'peak': START_EQUITY,
        'max_drawdown_pct': 0.0,
        'closed': 0,
        'wins': 0,
        'losses': 0,
        'gross_profit': 0.0,
        'gross_loss': 0.0,
        'last_hour': ((now_ms - 5000) // HOUR - 1) * HOUR,
        'open': None,
        'paused': False,
        'pause_reason': None,
        'created_utc': iso(now_ms),
        'last_signal': None
    }


def evaluate_signal(one, four, hour_open_ms):
    """Exact backtest H1_CHANNEL20 filter on latest CLOSED 1h + as-of closed 4h."""
    if len(one) < 230 or len(four) < 240:
        return None, 'indicator history incomplete'
    if one[-1][0] != hour_open_ms:
        return None, 'wrong hour candle'
    decision = hour_open_ms + HOUR
    # Higher-timeframe candles must be fully closed when 1H candle closes.
    four_times = [r[0] for r in four]
    j = bisect.bisect_right(four_times, decision - FOUR) - 1
    if j < 220:
        return None, '4h history incomplete'
    f1 = rules.features(one)
    f4 = rules.features(four)
    ev = rules.make_signal('ETHUSDT', MODEL, one, len(one) - 1, f1, f4, j)
    if ev is None or ev['time'] != decision:
        return None, 'filter conditions not satisfied'
    return ev, 'candidate'


class PaperExperiment:
    def __init__(self, now_ms=None, state_file=STATE, history_file=HISTORY):
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        self.state_file = Path(state_file)
        self.history_file = Path(history_file)
        if self.state_file.exists():
            self.state = engine.load_json(self.state_file, {})
            if self.state.get('version') != 1:
                raise RuntimeError('Incompatible ETH forward-paper state; not reset automatically')
        else:
            self.state = default_state(now_ms)
            self.save()

    def save(self):
        engine.save_json(self.state_file, self.state)

    def record(self, entry):
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with self.history_file.open('a', encoding='utf-8') as file:
            file.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def summary(self):
        s = self.state
        gain = 100 * (s['equity'] / START_EQUITY - 1)
        pf = (s['gross_profit'] / -s['gross_loss']
              if s['gross_loss'] < 0 else None)
        return (f'ETH 1H Donchian20 forward-paper: {s["closed"]} kapanan, '
                f'{s["wins"]} kazanc / {s["losses"]} kayip, '
                f'net {gain:+.3f}%, bakiye {s["equity"]:.2f} USDT, '
                f'profit factor {pf:.2f}' if pf is not None else
                f'ETH 1H Donchian20 forward-paper: {s["closed"]} kapanan, '
                f'net {gain:+.3f}%, bakiye {s["equity"]:.2f} USDT. '
                'Profit factor icin yeterli kayip yok.')

    def pause(self, reason, now_ms):
        if self.state['paused']:
            return []
        self.state['paused'] = True
        self.state['pause_reason'] = reason
        self.save()
        self.record({'event': 'PAUSED', 'utc': iso(now_ms), 'reason': reason})
        return ['ETH 1H DENEYSEL SANAL TAKIP DURDURULDU: veri boslugu / '
                'gecersiz akis. Eski islemin sonucu otomatik kar sayilmadi. '
                'Kontrol gerekli. Gercek emir YOK.']

    def close(self, bar, reason, exit_raw, now_ms):
        pos = self.state['open']
        d = pos['direction']
        qty = pos['qty']
        exit_fill = exit_raw * (1 - d * SLIP)
        pnl = ((exit_fill - pos['entry']) * d * qty -
               FEE * qty * (pos['entry'] + exit_fill))
        equity = self.state['equity'] + pnl
        self.state['equity'] = equity
        self.state['peak'] = max(self.state['peak'], equity)
        self.state['max_drawdown_pct'] = min(
            self.state['max_drawdown_pct'],
            100 * (equity / self.state['peak'] - 1))
        self.state['closed'] += 1
        if pnl > 0:
            self.state['wins'] += 1
            self.state['gross_profit'] += pnl
        else:
            self.state['losses'] += 1
            self.state['gross_loss'] += pnl
        self.state['open'] = None
        self.save()
        event = {
            'event': 'CLOSE', 'opened_utc': iso(pos['time']),
            'closed_utc': iso(now_ms), 'bar_utc': iso(bar[0]),
            'symbol': 'ETHUSDT', 'model': MODEL,
            'direction': 'LONG' if d == 1 else 'SHORT',
            'reason': reason, 'entry': pos['entry'],
            'exit_fill': exit_fill, 'qty': qty,
            'fee_per_side': FEE, 'slip_per_side': SLIP,
            'net_pnl_usdt': round(pnl, 6),
            'equity_usdt': round(equity, 6)
        }
        self.record(event)
        return (f'ETH 1H Donchian20 | SANAL {reason}\n'
                f'{event["direction"]} | Net {pnl:+.2f} USDT\n'
                f'{self.summary()}\n'
                'Sadece varsayimsal; gercek emir YOK.')

    def process_bars(self, rows, now_ms):
        pos = self.state.get('open')
        if not pos or self.state['paused']:
            return []
        if not rows:
            return self.pause('empty 5m history', now_ms)
        next_open = pos['last_bar'] + FIVE
        if rows[0][0] > next_open:
            return self.pause('missing closed 5m candles; cannot verify stop', now_ms)
        messages = []
        for bar in rows:
            if bar[0] <= pos['last_bar']:
                continue
            if bar[0] < pos['entry_bar']:
                pos['last_bar'] = bar[0]
                continue
            if bar[0] != pos['last_bar'] + FIVE:
                return self.pause('5m discontinuity while trade open', now_ms)
            if not all(math.isfinite(float(v)) and float(v) > 0 for v in bar[1:5]):
                return self.pause('invalid 5m candle', now_ms)
            _, opening, high, low, closing, _vol = bar
            d = pos['direction']
            stop_hit = low <= pos['stop'] if d == 1 else high >= pos['stop']
            take_hit = high >= pos['target'] if d == 1 else low <= pos['target']
            reason, exit_raw = None, None
            if stop_hit:  # stop first if intrabar execution path ambiguous
                reason = 'STOP'
                exit_raw = min(opening, pos['stop']) if d == 1 else max(opening, pos['stop'])
            elif take_hit:
                reason = 'TARGET'
                exit_raw = pos['target']
            elif bar[0] >= pos['deadline_ms']:
                reason = 'TIME'
                exit_raw = opening
            if reason:
                messages.append(self.close(bar, reason, exit_raw, bar[0]))
                return messages
            pos['last_bar'] = bar[0]
            self.save()
        return messages

    def on_market(self, market, now_ms, eth_price=None, eth_quote_ms=None):
        """On each NEW 5m closed candle; run only when market is fresh and contiguous."""
        if self.state['paused']:
            return []
        five = market.get('5m', [])
        one = market.get('1H', [])
        four = market.get('4H', [])
        notifications = self.process_bars(five, now_ms)
        if self.state['paused']:
            return notifications
        # At most one paper position at a time; monitor it, do not stack.
        if not one:
            return notifications
        current_hour = ((now_ms - 5000) // HOUR - 1) * HOUR
        if current_hour <= self.state['last_hour']:
            return notifications
        # Suppress signals from offline periods.
        decision = current_hour + HOUR
        if now_ms - decision > MAX_SIGNAL_DELAY_MS:
            self.state['last_hour'] = current_hour
            self.save()
            return notifications
        if one[-1][0] != current_hour:
            # Let API catch up on next polling pass.
            return notifications
        # At each 1H decision use the most recently CLOSED 4H candle.
        # If it just closed but Bitget API still lags, DO NOT use an older bar.
        expected_four = (decision // FOUR) * FOUR - FOUR
        if not four or four[-1][0] != expected_four:
            return notifications
        self.state['last_hour'] = current_hour
        self.save()
        if self.state['open']:
            return notifications
        candidate, reason = evaluate_signal(one, four, current_hour)
        if not candidate:
            return notifications
        if (eth_price is None or eth_quote_ms is None or
                now_ms - eth_quote_ms > QUOTE_MAX_AGE_MS or
                eth_quote_ms > now_ms or not math.isfinite(eth_price) or eth_price <= 0):
            self.record({'event':'SIGNAL_SKIPPED','utc':iso(now_ms),
                         'reason':'fresh ETH quote unavailable','signal':candidate})
            return notifications
        if abs(eth_price - candidate['reference']) > MAX_ENTRY_DRIFT_ATR * candidate['atr']:
            self.record({'event':'SIGNAL_SKIPPED','utc':iso(now_ms),
                         'reason':'price drift from close >0.5 ATR','signal':candidate})
            return notifications
        d = candidate['direction']
        entry = eth_price * (1 + d * SLIP)
        risk = (entry - candidate['stop']) * d
        reward = (candidate['target'] - entry) * d
        if risk <= 0 or reward <= 0:
            self.record({'event':'SIGNAL_SKIPPED','utc':iso(now_ms),
                         'reason':'stop or target already crossed','signal':candidate})
            return notifications
        equity = self.state['equity']
        qty = min(equity * MAX_RISK / risk, equity * MAX_NOTIONAL / entry)
        if qty <= 0:
            return notifications
        first_bar = now_ms // FIVE * FIVE
        pos = {
            'direction': d, 'entry': entry, 'stop': candidate['stop'],
            'target': candidate['target'], 'qty': qty,
            'time': now_ms, 'signal_candle': current_hour,
            'entry_bar': first_bar, 'last_bar': first_bar-FIVE,
            'deadline_ms': first_bar + candidate['timeout'],
            'reference': candidate['reference'], 'model': MODEL
        }
        self.state['open'] = pos
        self.state['last_signal'] = {'direction':d,'hour_open':current_hour}
        self.save()
        self.record({'event':'OPEN','utc':iso(now_ms),'symbol':'ETHUSDT',
                     'model':MODEL, 'signal_candle':iso(current_hour),
                     'direction':'LONG' if d == 1 else 'SHORT',
                     'entry':entry,'reference_close':candidate['reference'],
                     'stop':candidate['stop'],'target':candidate['target'],
                     'qty':qty,'simulated_notional_usdt':entry*qty,
                     'fee_per_side':FEE,'slip_per_side':SLIP,
                     'equity_before_usdt':equity})
        notifications.append(
            f'ETH 1H Donchian20 | DENEYSEL SANAL '
            f'{"LONG" if d == 1 else "SHORT"}\n'
            f'Tahmini giris: {entry:.2f} | Stop: {candidate["stop"]:.2f}\n'
            f'Hedef: {candidate["target"]:.2f}\n'
            f'Pozisyon: {entry * qty:.2f} USDT nominal, 1x sinir.\n'
            f'Sadece forward-test: kar dogrulanmadi, gercek emir YOK.')
        return notifications
