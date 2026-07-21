#!/usr/bin/env python3
"""边际扫描器：找"极端条件触发后、未来20日高胜率"的大机会规则（左侧抄底）。

不是 ML 分类器（那被迫在模糊地带排序，AUC≈0.5）。这里只挖分布尾部的极端事件，
统计每条规则触发后的条件概率 + edge，用 Wilson 置信下界排序以杜绝小样本假信号。

对每条规则报告：
  N           触发次数（样本量——生死线）
  P(up20)     未来20日上涨概率
  wilson_lb   胜率的 95% Wilson 置信下界（小样本自动打折，排序主指标）
  edge        P(up20) − 无条件基准（剔除牛市普涨偏差后的真实超额）
  ret20       平均20日收益
  tb_win      三重障碍成功率（+3ATR 先于 −2ATR，"大涨"口径）
  payoff      三重障碍盈亏比（tb_long_ret 赢均值/亏均值）

只保留 N ≥ MIN_N 的规则，按 wilson_lb 降序。输出榜单 + edge_rules.csv。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "model_dataset.csv"
MIN_N = 20          # 样本量门槛：低于此不可信，直接剔除
Z = 1.96            # 95% 置信


def wilson_lower(k: int, n: int, z: float = Z) -> float:
    """二项比例 k/n 的 Wilson 置信下界。n 小则下界远低于点估计（自动惩罚小样本）。"""
    if n == 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (center - margin) / denom


def build_signals(d: pd.DataFrame) -> dict:
    """信号族：单条件(超卖/回撤/支撑) + 组合(超卖×趋势/支撑过滤)。"""
    # 现算：50周线(≈250日均线)贴合度、连续下跌天数
    d["ma250"] = d.groupby("ticker")["close"].transform(lambda s: s.rolling(250).mean())
    d["px_ma250"] = d["close"] / d["ma250"] - 1
    down = (d["ret_1d"] < 0).astype(int)
    d["down_streak"] = down.groupby((down != down.shift()).cumsum()).cumcount() + 1
    d.loc[d["ret_1d"] >= 0, "down_streak"] = 0

    return {
        # —— 深度超卖（单条件）——
        "RSI<20": d.rsi14 < 20,
        "RSI<25": d.rsi14 < 25,
        "RSI<30": d.rsi14 < 30,
        "CCI<-200": d.cci20 < -200,
        "CCI<-150": d.cci20 < -150,
        "破布林下轨(pctb<0)": d.boll_pctb < 0,
        "WillR<-95": d.willr14 < -95,
        "连跌≥5日": d.down_streak >= 5,
        # —— 深度回撤 ——
        "距52周高<-25%": d.dist_52w_high < -0.25,
        "距52周高<-35%": d.dist_52w_high < -0.35,
        # —— 关键均线支撑（单独通常无效，作对照）——
        "回踩ma200(±2%)": d.px_ma200.abs() < 0.02,
        "回踩50周线(±3%)": d.px_ma250.abs() < 0.03,
        # —— 组合：超卖 × 趋势/支撑/回撤过滤 ——
        "RSI<30 & 价在ma200上(顺势回调)": (d.rsi14 < 30) & (d.px_ma200 > 0),
        "RSI<25 & 距52周高<-20%": (d.rsi14 < 25) & (d.dist_52w_high < -0.20),
        "RSI<30 & CCI<-150": (d.rsi14 < 30) & (d.cci20 < -150),
        "破下轨 & RSI<30": (d.boll_pctb < 0) & (d.rsi14 < 30),
        "RSI<30 & 回踩50周线(±5%)": (d.rsi14 < 30) & (d.px_ma250.abs() < 0.05),
        "RSI<30 & 连跌≥4日": (d.rsi14 < 30) & (d.down_streak >= 4),
    }


def main():
    d = pd.read_csv(DATA)
    d = d[d.fwd_ret_20d.notna()].copy()
    d["up20"] = (d.fwd_ret_20d > 0).astype(int)
    base = d.up20.mean()

    signals = build_signals(d)
    rows = []
    for name, mask in signals.items():
        s = d[mask.fillna(False)]
        n = len(s)
        if n < MIN_N:
            rows.append((name, n, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, False))
            continue
        k = int(s.up20.sum())
        p = k / n
        lb = wilson_lower(k, n)
        ret20 = np.expm1(s.fwd_ret_20d.mean())
        tb = s[s.tb_long.notna()]
        tb_win = tb.tb_long.mean() if len(tb) else np.nan
        wins = tb.loc[tb.tb_long == 1, "tb_long_ret"]
        losses = tb.loc[tb.tb_long == 0, "tb_long_ret"]
        payoff = wins.mean() / abs(losses.mean()) if len(losses) and losses.mean() != 0 else np.nan
        rows.append((name, n, p, lb, p - base, ret20, tb_win, payoff, True))

    res = pd.DataFrame(rows, columns=["rule", "N", "p_up20", "wilson_lb", "edge",
                                      "ret20", "tb_win", "payoff", "ok"])
    ranked = res[res.ok].sort_values("wilson_lb", ascending=False).reset_index(drop=True)

    print(f"无条件基准 P(未来20日上涨) = {base:.1%}  (n={len(d)})  ← 判断 edge 的尺子")
    print(f"样本门槛 N≥{MIN_N}，按 Wilson 95% 置信下界排序（小样本自动降权）\n")
    print(f"{'规则':<32}{'N':>5}{'上涨概率':>9}{'置信下界':>9}{'edge':>8}"
          f"{'平均20日':>9}{'障碍胜率':>9}{'盈亏比':>7}")
    print("-" * 96)
    for _, r in ranked.iterrows():
        tb = f"{r.tb_win:.0%}" if pd.notna(r.tb_win) else "—"
        pf = f"{r.payoff:.2f}" if pd.notna(r.payoff) else "—"
        flag = "  ★" if (r.wilson_lb >= 0.70 and r.edge >= 0.12) else ""
        print(f"{r.rule:<32}{int(r.N):>5}{r.p_up20:>8.1%}{r.wilson_lb:>9.1%}"
              f"{r.edge:>+8.1%}{r.ret20:>+9.1%}{tb:>9}{pf:>7}{flag}")

    skipped = res[~res.ok]
    if len(skipped):
        print(f"\n样本不足(N<{MIN_N})被剔除: "
              + ", ".join(f"{r.rule}(N={int(r.N)})" for _, r in skipped.iterrows()))

    print("\n★ = Wilson下界≥70% 且 edge≥+12%：样本量够、胜率稳、超额显著的可交易强规则")
    ranked.to_csv(ROOT / "edge_rules.csv", index=False)
    print("已存 edge_rules.csv")


if __name__ == "__main__":
    sys.exit(main())
