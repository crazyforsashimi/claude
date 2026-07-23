#!/usr/bin/env python3
"""per-ticker RSI 买入/强买入阈值校准 → rsi_thresholds.json / .js（邮件/工具/回测三端读）。

动机：固定 RSI<20/25 对强趋势股(GEV/NVDA 等 5 年碰不到 20)几乎不触发。用每只标的过去5年数据
校准个性化阈值——但只对"放宽后仍稳"的标的放宽，避免摊薄信号质量。

分类规则(对31只一视同仁)：候选阈值 16/18/…/30，按 20 日回溯——
  · 买入档：触发≥8 且 Wilson 下界≥60% 的候选里，选下界最高的阈值；都不满足→无买入档(靠破布林/默认)。
  · 强买入档：仅当有买入档时，在更严(阈值<买入)、触发≥5、原始胜率≥90% 的候选里选下界最高。
Wilson 下界是核心尺(重罚小样本，防"N=3 假100%")。门槛卡 60=最稳的一档。
⚠️ 同数据选阈值又评估，有过拟合乐观偏差，真实样本外会打折，实盘观察。

输出 {tk: {"strong": int|None, "buy": int}}，只含有买入档的标的；其余标的邮件/工具用默认 20/25。
重跑：python gen_rsi_thresholds.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "output" / "model_dataset.csv"
CAND = [16, 18, 20, 22, 24, 26, 28, 30]
BUY_LB, BUY_N = 0.60, 8          # 买入档：Wilson 下界≥60%、触发≥8
STRONG_RATE, STRONG_N = 0.90, 5  # 强买入档：原始胜率≥90%、触发≥5、且严于买入


def wilson_lb(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d


def main():
    d = pd.read_csv(DATA).sort_values(["ticker", "date"]).reset_index(drop=True)
    d["fwd20"] = d.groupby("ticker")["close"].shift(-20) / d["close"] - 1
    d = d[d["fwd20"].notna()].copy()

    out = {}
    for tk, g in d.groupby("ticker"):
        st = {}
        for t in CAND:
            s = g[g.rsi14 < t]
            n = len(s)
            st[t] = (n, (s.fwd20 > 0).mean() if n else 0.0, wilson_lb(int((s.fwd20 > 0).sum()), n))
        buy_c = [t for t in CAND if st[t][0] >= BUY_N and st[t][2] >= BUY_LB]
        buy = max(buy_c, key=lambda t: st[t][2]) if buy_c else None
        strong = None
        if buy is not None:
            sc = [t for t in CAND if t < buy and st[t][0] >= STRONG_N and st[t][1] >= STRONG_RATE]
            strong = max(sc, key=lambda t: st[t][2]) if sc else None
        if buy is not None:
            out[tk] = {"strong": strong, "buy": buy}

    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output" / "rsi_thresholds.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    (ROOT / "rsi_thresholds.js").write_text(f"window.RSI_THR={compact};\n", encoding="utf-8")
    dual = {k: v for k, v in out.items() if v["strong"]}
    print(f"共 {len(out)} 只有 RSI 档（{len(dual)} 只双档）→ rsi_thresholds.js + output/rsi_thresholds.json")
    for tk, v in sorted(out.items()):
        print(f"  {tk:<6} 强买入 RSI<{v['strong'] if v['strong'] else '—(无)'}  ·  买入 RSI<{v['buy']}")


if __name__ == "__main__":
    main()
