#!/usr/bin/env python3
"""per-ticker 信号校准（RSI 阈值 + 布林下轨周期）→ signal_config.json / .js（邮件/工具/回测三端读）。

理念：固定 RSI<20/25、固定100日布林对不同标的效果天差地别(强趋势股 RSI 碰不到、100布林胜率塌)。
用每只标的过去5年数据 per-ticker 校准——**N 小不是问题(极端罕见=大机会)**，故用「原始胜率(多持有期
达标)」作硬指标，而非重罚小样本的 Wilson 下界。

判定标准(对31只一视同仁，看破位后 5/10/20 日回溯方向胜率)：
  · 强买入：≥2 个 >95% 且 三个都 >55%(第三窗口地板，滤"两高一塌")。
  · 买入：  ≥2 个 >80% 且 三个都 >55%。
两类信号：
  · RSI：候选阈值 14…30。买入取满足的最宽阈值；强买入取更严(阈值<买入)的最宽。
  · 布林下轨(close ≤ MA_N − 2σ)：候选周期 20/50/100/150/200。买入取满足的最小周期(易触发);
    强买入取更深(周期≥买入)的最大周期。触发次数：RSI 不限(N≥1)，布林 买入≥5/强买入≥3(布林更需样本)。
均线支撑经测试基本不成立(触及/下穿 MA 反弹胜率不达标、仅1~2只)，故不纳入。
⚠️ 同数据选参数又评估，有过拟合乐观偏差；小样本高胜率作"极端信号提示"、别当可交易 edge，实盘打折。

输出 {tk: {"rsi":{"s":int|None,"b":int|None}, "boll":{"s":int|None,"b":int|None}}}，只含至少一档的标的。
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
    """5/10/20 日胜率 rs 是否满足：≥2 个 > hi 且 三个都 > FLOOR。"""
    return len(rs) == 3 and sum(r > hi for r in rs) >= 2 and min(rs) > FLOOR


def main():
    d = pd.read_csv(DATA).sort_values(["ticker", "date"]).reset_index(drop=True)
    for h in (5, 10, 20):
        d[f"fwd{h}"] = d.groupby("ticker")["close"].shift(-h) / d["close"] - 1
    for N in BOLL_CAND:
        ma = d.groupby("ticker")["close"].transform(lambda s: s.rolling(N).mean())
        sd = d.groupby("ticker")["close"].transform(lambda s: s.rolling(N).std())
        d[f"boll{N}"] = d.close <= ma - 2 * sd
    d = d[d["fwd20"].notna()].copy()

    def rates(sub):
        return [round((sub[f"fwd{h}"] > 0).mean() * 100) for h in (5, 10, 20)] if len(sub) else [0, 0, 0]

    def calib_rsi(g):
        st = {t: (len(g[g.rsi14 < t]), rates(g[g.rsi14 < t])) for t in RSI_CAND}
        buy_c = [t for t in RSI_CAND if st[t][0] >= 1 and qualifies(st[t][1], BUY_HI)]
        buy = max(buy_c) if buy_c else None
        sc = [t for t in RSI_CAND if st[t][0] >= 1 and qualifies(st[t][1], STRONG_HI) and (buy is None or t < buy)]
        return (max(sc) if sc else None), buy

    def calib_boll(g):
        st = {N: (len(g[g[f"boll{N}"]]), rates(g[g[f"boll{N}"]])) for N in BOLL_CAND}
        buy_c = [N for N in BOLL_CAND if st[N][0] >= 5 and qualifies(st[N][1], BUY_HI)]
        buy = min(buy_c) if buy_c else None                       # 布林买入：满足里最小周期(易触发)
        sc = [N for N in BOLL_CAND if st[N][0] >= 3 and qualifies(st[N][1], STRONG_HI) and (buy is None or N >= buy)]
        return (max(sc) if sc else None), buy                     # 强买入：满足里最深周期

    out = {}
    for tk, g in d.groupby("ticker"):
        rs, rb = calib_rsi(g)
        bs, bb = calib_boll(g)
        if any(x is not None for x in (rs, rb, bs, bb)):
            out[tk] = {"rsi": {"s": rs, "b": rb}, "boll": {"s": bs, "b": bb}}

    # 进仓库：signal_config.json 供 Python 三端(daily_alert/build_ticker_stats/gen_backtest_table)读；
    #        signal_config.js 供工具 index.html 读(window.SIGNAL_CFG)
    (ROOT / "signal_config.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    (ROOT / "signal_config.js").write_text(f"window.SIGNAL_CFG={compact};\n", encoding="utf-8")
    print(f"共 {len(out)} 只有信号档 → signal_config.js + output/signal_config.json\n")
    print(f"{'标的':<6}{'RSI强':>7}{'RSI买':>7}{'布林强':>8}{'布林买':>8}")
    for tk, v in sorted(out.items()):
        r, b = v["rsi"], v["boll"]
        fmt = lambda x, u="": f"<{x}{u}" if x else "—"
        print(f"{tk:<6}{fmt(r['s']):>7}{fmt(r['b']):>7}{fmt(b['s'],'日'):>8}{fmt(b['b'],'日'):>8}")


if __name__ == "__main__":
    main()
