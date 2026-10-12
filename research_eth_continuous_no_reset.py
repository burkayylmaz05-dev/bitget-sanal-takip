# -*- coding: utf-8 -*-
"""Uninterrupted frozen ETH 4H EMA50/EMA200 strategy retrospective audit.

2021 Jul--2022 Jan warmup, trade Jan 1 2022--Oct 11 2026 without
six-month balance resets. Use frozen research_v102_low_churn exact model
and public Bitget futures 4h OHLC. Compare taker 6bps + slip 3bps each
side against no fees and 2x fees; 1x cap .5% stop-risk, max 30d hold.
Caveat: funding unavailable for earlier years; cannot claim net profits
realisable. Retrospective strategy was SCREENED on 2025-2026.
"""
import datetime as dt
import json
import research_backtest as api
import research_v102_low_churn as model

def main():
    warmup=model.date("2021-07-01")
    start=model.date("2022-01-01")
    end=model.date("2026-10-11")
    rows,calls=api.history("ETHUSDT","4H",warmup,end)
    indicators=model.events(rows)
    params=indicators[0],indicators[1],indicators[2],"EMA50_200_BOTH",start,end
    standard=model.sim(rows,*params)
    zero=model.sim(rows,*params,fee=0,slip=0)
    double=model.sim(rows,*params,fee=model.FEE*2,slip=model.SLIP*2)
    three=model.sim(rows,*params,fee=model.FEE*3,slip=model.SLIP*3)
    first=next(x for x in rows if x[0]>=start)
    last=next(x for x in reversed(rows) if x[0]<end)
    hold=(last[4]/first[1]-1)*100
    print("CONTINUOUS_ETH_JSON",json.dumps({
        "history_start_utc":"2021-07-01",
        "trading_start_utc":"2022-01-01",
        "trading_end_utc":"2026-10-11",
        "sample_bars":len(rows),
        "raw_buyhold_pct_not_risk_matched":round(hold,3),
        "strategy_0x_cost":zero,
        "strategy_assumed_cost":standard,
        "strategy_2x_cost":double,
        "strategy_3x_cost":three,
        "funding_included":False,"already_screened_on_2026":True,
        "live_orders":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
