#!/usr/bin/env python3
"""per-ticker RSI 买入/强买入阈值校准 → rsi_thresholds.json / .js（邮件/工具/回测三端读）。

动机：固定 RSI<20/25 对强趋势股(GEV/NVDA 等 5 年碰不到 20)几乎不触发。用每只标的过去5年数据
校准个性化阈值。理念：**N 小不是问题——N 小恰说明机会极端罕见**，故用「原始胜率(多持有期达标)」
作硬指标，而非重罚小样本的 Wilson 下界。

分类规则(对31只一视同仁，候选阈值 14/16/…/30，看 5/10/20 日回溯方向胜率)：
  · 买入档：5/10/20 日里 **≥2 个 >85% 且 三个都 >55%**(第三窗口地板，滤掉"两高一塌") → 满足者取最宽阈值。
  · 强买入档：**≥2 个 >95% 且 三个都 >55%**，且严于买入(阈值<买入) → 满足者取最宽。
  不限触发次数(N≥1 即可)。因 >95 ⟹ >85，强买入阈值天然 ≤ 买入。
⚠️ 同数据选阈值又评估，有过拟合乐观偏差；小样本高胜率作"极端信号提示"、别当可交易 edge，实盘打折。

输出 {tk: {"strong": int|None, "buy": int|None}}，只含有买入或强买入档的标的；其余用默认 20/25。
重跑：python gen_rsi_thresholds.py
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "output" / "model_dataset.csv"
CAND = [14, 16, 18, 20, 22, 24, 26, 28, 30]
FLOOR = 55            # 三个持有期都必须 > 55%（第三窗口地板）
STRONG_HI, BUY_HI = 95, 85


def qualifies(rs, hi):
    """5/10/20 日胜率 rs 是否满足：≥2 个 > hi 且 三个都 > FLOOR。"""
    return sum(r > hi for r in rs) >= 2 and min(rs) > FLOOR


def main():
    d = pd.read_csv(DATA).sort_values(["ticker", "date"]).reset_index(drop=True)
    for h in (5, 10, 20):
        d[f"fwd{h}"] = d.groupby("ticker")["close"].shift(-h) / d["close"] - 1
    d = d[d["fwd20"].notna()].copy()

    out = {}
    for tk, g in d.groupby("ticker"):
        rate = {}
        for t in CAND:
            s = g[g.rsi14 < t]
            rate[t] = [round((s[f"fwd{h}"] > 0).mean() * 100) for h in (5, 10, 20)] if len(s) else [0, 0, 0]
        buy_c = [t for t in CAND if len(g[g.rsi14 < t]) >= 1 and qualifies(rate[t], BUY_HI)]
        buy = max(buy_c) if buy_c else None
        strong_c = [t for t in CAND if len(g[g.rsi14 < t]) >= 1 and qualifies(rate[t], STRONG_HI)
                    and (buy is None or t < buy)]
        strong = max(strong_c) if strong_c else None
        if buy is not None or strong is not None:
            out[tk] = {"strong": strong, "buy": buy}

    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output" / "rsi_thresholds.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    (ROOT / "rsi_thresholds.js").write_text(f"window.RSI_THR={compact};\n", encoding="utf-8")
    dual = {k: v for k, v in out.items() if v["strong"] and v["buy"]}
    print(f"共 {len(out)} 只有 RSI 档（{len(dual)} 只双档）→ rsi_thresholds.js + output/rsi_thresholds.json")
    for tk, v in sorted(out.items()):
        print(f"  {tk:<6} 强买入 RSI<{v['strong'] if v['strong'] else '—'}  ·  买入 RSI<{v['buy'] if v['buy'] else '—'}")


if __name__ == "__main__":
    main()
