#!/usr/bin/env python3
"""per-ticker 双窗口信号校准（5年 + 2年，各含 RSI 阈值 + 布林周期）→ signal_config.json / .js。

动机：固定阈值对不同标的效果天差地别；且**5年门槛在近期市场可能过严、难触发**(如 NEE 5年 RSI<18)。
故每标的算两套:5年(长期极端、质量硬) + 2年(近期敏感、抓当下情绪)。触发任一套即提示、标注是哪套;
两套共振("5年+2年都触发")信号意义更强。

判定标准(两窗口相同，看破位后 5/10/20 日回溯方向胜率)：
  · 强买入：≥2 个 >95% 且 三个都 >55%(第三窗口地板)。
  · 买入：  ≥2 个 >80% 且 三个都 >55%。
两类信号:RSI(候选阈值 14–30) + 布林下轨(候选周期 20/50/100/150/200)。触发次数:RSI 不限(N≥1)，
布林 买入≥5/强买入≥3。均线支撑经测试不成立、已弃。
⚠️ 同数据选参数又评估，有过拟合乐观偏差;2年样本更少、且近两年上涨市含更多 beta，参考性弱于5年，实盘打折。

输出 {tk: {"5y":{"rsi":{"s","b"},"boll":{"s","b"}}, "2y":{...}}}，只含至少一套一档的标的。
重跑：python gen_signal_config.py
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "output" / "model_dataset.csv"
RSI_CAND = [14, 16, 18, 20, 22, 24, 26, 28, 30]
BOLL_CAND = [20, 50, 100, 150, 200]
FLOOR, STRONG_HI, BUY_HI = 55, 95, 80


def qualifies(rs, hi):
    return len(rs) == 3 and sum(r > hi for r in rs) >= 2 and min(rs) > FLOOR


def rates(sub):
    return [round((sub[f"fwd{h}"] > 0).mean() * 100) for h in (5, 10, 20)] if len(sub) else [0, 0, 0]


def calib(g):
    """对一个标的的一个数据窗口 g，校准 RSI 阈值 + 布林周期 → {"rsi":{"s","b"},"boll":{"s","b"}}。"""
    rst = {t: (len(g[g.rsi14 < t]), rates(g[g.rsi14 < t])) for t in RSI_CAND}
    rb = max([t for t in RSI_CAND if rst[t][0] >= 1 and qualifies(rst[t][1], BUY_HI)], default=None)
    rs = max([t for t in RSI_CAND if rst[t][0] >= 1 and qualifies(rst[t][1], STRONG_HI)
              and (rb is None or t < rb)], default=None)
    bst = {N: (len(g[g[f"boll{N}"]]), rates(g[g[f"boll{N}"]])) for N in BOLL_CAND}
    bb = min([N for N in BOLL_CAND if bst[N][0] >= 5 and qualifies(bst[N][1], BUY_HI)], default=None)
    bs = max([N for N in BOLL_CAND if bst[N][0] >= 3 and qualifies(bst[N][1], STRONG_HI)
              and (bb is None or N >= bb)], default=None)
    return {"rsi": {"s": rs, "b": rb}, "boll": {"s": bs, "b": bb}}


def has_slot(c):
    return any(c["rsi"][k] for k in ("s", "b")) or any(c["boll"][k] for k in ("s", "b"))


def main():
    d = pd.read_csv(DATA).sort_values(["ticker", "date"]).reset_index(drop=True)
    d["dt"] = pd.to_datetime(d["date"])
    for h in (5, 10, 20):
        d[f"fwd{h}"] = d.groupby("ticker")["close"].shift(-h) / d["close"] - 1
    for N in BOLL_CAND:                          # 布林在完整序列上算(rolling backward，过滤末尾不影响)
        ma = d.groupby("ticker")["close"].transform(lambda s: s.rolling(N).mean())
        sd = d.groupby("ticker")["close"].transform(lambda s: s.rolling(N).std())
        d[f"boll{N}"] = d.close <= ma - 2 * sd
    d = d[d["fwd20"].notna()].copy()
    cutoff = d["dt"].max() - pd.DateOffset(years=2)   # 2年窗口:统计近两年的触发点(布林周期仍用完整历史算)

    out = {}
    for tk, g in d.groupby("ticker"):
        c5 = calib(g)
        c2 = calib(g[g["dt"] >= cutoff])
        if has_slot(c5) or has_slot(c2):
            out[tk] = {"5y": c5, "2y": c2}

    (ROOT / "signal_config.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    (ROOT / "signal_config.js").write_text(f"window.SIGNAL_CFG={compact};\n", encoding="utf-8")
    n5 = sum(has_slot(v["5y"]) for v in out.values())
    n2 = sum(has_slot(v["2y"]) for v in out.values())
    print(f"共 {len(out)} 只有信号档(5年 {n5} 只 · 2年 {n2} 只) → signal_config.js + signal_config.json")


if __name__ == "__main__":
    main()
