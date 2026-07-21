#!/usr/bin/env python3
"""生成「每标的-每信号」的历史回溯统计表 → output/ticker_stats.json（并打印，供嵌入 index.html / daily_alert.py）。

用于大机会提示里在分组率之外，额外显示该标的自己的历史成功率(如实带样本数 N)。
N 小(甚至=1)也保留——它本身传递信息：该信号在这只票上极罕见=极端。可靠性由 N 自证，不冒充 edge。

每个标的只存它按 Tier2 分组实际会用到的信号：
  稳健组(非HI_VOL)：rsi20(RSI<20) / rsi25(RSI<25) / b100(破100日布林)
  动量·趋势回调组(MOM_DIP)：dip(破日线布林下轨且价在MA200上)
  动量·大支撑组(MOM_BIG)：b100(破100日布林)
  NET/COIN：无信号，不收录
值为 [N, 上涨率%]（触发后 20 日上涨概率；N=0 存 [0,null]）。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "output" / "model_dataset.csv"

HI_VOL = {"LEU", "COIN", "NET", "SNOW", "TSLA", "AMD", "GEV", "MU", "NVDA", "BABA", "CEG", "VST", "AVGO"}
MOM_DIP = {"NVDA", "AVGO", "MU", "AMD", "GEV", "CEG", "LEU", "VST"}
MOM_BIG = {"SNOW", "TSLA", "BABA"}


def main():
    d = pd.read_csv(DATA)
    d = d[d.fwd_ret_20d.notna()].copy()
    d["up"] = (d.fwd_ret_20d > 0).astype(int)
    d["ma100"] = d.groupby("ticker")["close"].transform(lambda s: s.rolling(100).mean())
    d["std100"] = d.groupby("ticker")["close"].transform(lambda s: s.rolling(100).std())
    d["b100"] = d.close <= d.ma100 - 2 * d.std100

    def stat(tk, mask):
        s = d[(d.ticker == tk) & mask.fillna(False)]
        n = len(s)
        return [n, round(s.up.mean() * 100)] if n else [0, None]

    sigs = {
        "rsi20": d.rsi14 < 20,
        "rsi25": d.rsi14 < 25,
        "b100": d.b100,
        "dip": (d.boll_pctb < 0) & (d.px_ma200 > 0),
    }
    out = {}
    for tk in d.ticker.unique():
        e = {}
        if tk in HI_VOL:
            if tk in MOM_DIP:
                e["dip"] = stat(tk, sigs["dip"])
            elif tk in MOM_BIG:
                e["b100"] = stat(tk, sigs["b100"])
            # NET/COIN 无信号
        else:
            e["rsi20"] = stat(tk, sigs["rsi20"])
            e["rsi25"] = stat(tk, sigs["rsi25"])
            e["b100"] = stat(tk, sigs["b100"])
        if e:
            out[tk] = e

    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output" / "ticker_stats.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    compact = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    print(f"共 {len(out)} 标的，写入 output/ticker_stats.json\n")
    print("=== 紧凑 JSON（粘进 index.html 的 TICKER_STATS 和 daily_alert.py）===")
    print(compact)


if __name__ == "__main__":
    raise SystemExit(main())
