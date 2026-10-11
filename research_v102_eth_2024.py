# -*- coding: utf-8 -*-
"""Frozen candidate ETH EMA50_200_BOTH, new 2024 historical date check.

This candidate was discovered after screening 2026, so 2024 is retrospective
robustness (not a prospective untouched trial). Exact original rules and
backtest engine imported; all periods fee + 2x fee stress. No orders.
"""
import datetime as dt
import json

import research_backtest as api
import research_v102_low_churn as frozen

def ts(s):
    return frozen.date(s)

def main():
    symbol='ETHUSDT'
    end=ts('2026-10-11')
    start=ts('2023-01-01')
    bars,n=api.history(symbol,'4H',start,end)
    directions,exits,atrs=frozen.events(bars)
    method='EMA50_200_BOTH'
    periods=[('2024_H1','2024-01-01','2024-07-01'),
             ('2024_H2','2024-07-01','2025-01-01'),
             ('2025_H1','2025-01-01','2025-07-01'),
             ('2025_H2','2025-07-01','2026-01-01'),
             ('2026_H1','2026-01-01','2026-07-01'),
             ('2026_H2','2026-07-01','2026-10-11')]
    out={}
    for label,a,b in periods:
        normal=frozen.sim(bars,directions,exits,atrs,method,ts(a),ts(b))
        stress=frozen.sim(bars,directions,exits,atrs,method,ts(a),ts(b),
                          fee=frozen.FEE*2,slip=frozen.SLIP*2)
        out[label]={'normal':normal,'stress_net_pct':stress['net_pct']}
        print('FROZEN_ETH',label,'pct',normal['net_pct'],
              'stress',stress['net_pct'],'trades',normal['closed'],
              'DD',normal['dd_pct'],flush=True)
    print('FROZEN_ETH_2024_2026_JSON',json.dumps({
        'method':'EMA50_200_BOTH','retrospective_screened_on_2026':True,
        'bars':len(bars),'periods':out,
        'note':'no funding, historical not forward'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
