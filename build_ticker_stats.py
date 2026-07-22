#!/usr/bin/env python3
"""生成「每标的-每信号」的历史回溯统计表 → output/ticker_stats.json（并打印，供嵌入 index.html / daily_alert.py）。

用于大机会提示里在分组率之外，额外显示该标的自己的历史成功率(如实带样本数 N)。
N 小(甚至=1)也保留——它本身传递信息：该信号在这只票上极罕见=极端。可靠性由 N 自证，不冒充 edge。

每个标的只存它按 Tier2 分组实际会用到的信号：
  稳健组(非HI_VOL)：rsi20(RSI<20) / rsi25(RSI<25) / b100(破100日布林)
  动量·趋势回调组(MOM_DIP)：dip(破日线布林下轨且价在MA200上)
  动量·大支撑组(MOM_BIG)：b100(破100日布林)
  NET/COIN：无信号，不收录
值为 [N, 5日, 10日, 20日 上涨率%]（同一批信号看不同持有期→看反弹节奏；N=0 存 [0,null,null,null]）。
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
    d = pd.read_csv(DATA).sort_values(["ticker", "date"]).reset_index(drop=True)
    # 先在完整连续序列上算 5/10/20 日前瞻收益(必须过滤前算，否则 shift 会跨越被删的末尾行)
    for h in (5, 10, 20):
        d[f"fwd{h}"] = d.groupby("ticker")["close"].shift(-h) / d["close"] - 1
    d = d[d["fwd20"].notna()].copy()     # 同批：以能算满 20 日的信号为准
    d["ma100"] = d.groupby("ticker")["close"].transform(lambda s: s.rolling(100).mean())
    d["std100"] = d.groupby("ticker")["close"].transform(lambda s: s.rolling(100).std())
    d["b100"] = d.close <= d.ma100 - 2 * d.std100

    def stat(tk, mask):
        s = d[(d.ticker == tk) & mask.fillna(False)]
        n = len(s)
        if not n:
            return [0, None, None, None]
        return [n] + [round((s[f"fwd{h}"] > 0).mean() * 100) for h in (5, 10, 20)]

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
            e["rsi20"] = stat(tk, sigs["rsi20"])     # 动量组也加 RSI 极端超卖档(罕见=极端、反弹最猛)
            e["rsi25"] = stat(tk, sigs["rsi25"])
            if tk in MOM_DIP:
                e["dip"] = stat(tk, sigs["dip"])
            elif tk in MOM_BIG:
                e["b100"] = stat(tk, sigs["b100"])
            # NET/COIN 现在有 rsi20/rsi25(破布林无效但深度超卖有效)
        else:
            e["rsi20"] = stat(tk, sigs["rsi20"])
            e["rsi25"] = stat(tk, sigs["rsi25"])
            e["b100"] = stat(tk, sigs["b100"])
        if e:
            out[tk] = e

    if len(out) < 25:   # 正常应 29 个标的；不足说明上游数据残缺，拒绝写表以免覆盖好数据
        raise SystemExit(f"❌ 只有 {len(out)} 个标的的统计，数据不完整，中止(不写 ticker_stats.js)")

    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output" / "ticker_stats.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    compact = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    # ticker_stats.js —— 工具 index.html 直接 <script src> 加载；进仓库，每月定时 Action 自动重跑更新
    (ROOT / "ticker_stats.js").write_text(f"window.TICKER_STATS={compact};\n", encoding="utf-8")
    print(f"共 {len(out)} 标的 → ticker_stats.js(工具) + output/ticker_stats.json")


if __name__ == "__main__":
    raise SystemExit(main())
