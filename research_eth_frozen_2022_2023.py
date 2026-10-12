# -*- coding: utf-8 -*-
"""ETH 4H EMA50/EMA200 candidate on older 2022-2023 history, frozen.

The strategy was originally screened on 2025-2026 and also inspected
on 2024. These older 2022/23 periods are retrospective robustness ONLY.
DO NOT modify any parameters based on their results.
Fee .06% + assumed slippage .03% EACH side; 2x stress; no funding
outside separate 88-day 2026 audit. No keys and no exchange orders.
"""
import json
import datetime as dt
import research_backtest as api
import research_v102_low_churn as model

symbol="ETHUSDT"
candidate="EMA50_200_BOTH"
def ts(s): return model.date(s)
PERIODS=[
    ("2022_H1","2022-01-01","2022-07-01"),
    ("2022_H2","2022-07-01","2023-01-01"),
    ("2023_H1","2023-01-01","2023-07-01"),
    ("2023_H2","2023-07-01","2024-01-01"),
]
def main():
    beginning=ts("2021-07-01")
    end=ts("2024-01-01")
    bars,pages=api.history(symbol,"4H",beginning,end)
    print("BITGET_REAL_CANDLES",len(bars),"oldest",dt.datetime.fromtimestamp(bars[0][0]/1000,dt.timezone.utc),"latest",dt.datetime.fromtimestamp(bars[-1][0]/1000,dt.timezone.utc),flush=True)
    result={}
    for label,lo,hi in PERIODS:
        if bars[0][0]>ts(lo)-300*model.FOUR: raise RuntimeError(f"Missing EMA200 warmup before {label}")
    dirs,exits,atrs=model.events(bars)
    for label,lo,hi in PERIODS:
        normal=model.sim(bars,dirs,exits,atrs,candidate,ts(lo),ts(hi))
        double=model.sim(bars,dirs,exits,atrs,candidate,ts(lo),ts(hi),fee=model.FEE*2,slip=model.SLIP*2)
        result[label]={"normal":normal,"double_cost":double}
        print("FROZEN_ETH_OLD",label,normal["net_pct"],"stress",double["net_pct"],"trades",normal["closed"],"wins",normal["wins"],flush=True)
    print("ETH_2022_2023_JSON",json.dumps({"symbol":symbol,"method":candidate,"results":result,
        "data_bars":len(bars),"warmup_start":"2021-07-01","funding_included":False,
        "retrospective_screened_2025_2026":True},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
