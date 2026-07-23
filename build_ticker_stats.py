#!/usr/bin/env python3
"""生成「每标的-每 per-ticker 信号档」的历史回溯统计表 → ticker_stats.js（工具 index.html 加载）。

信号档来自 signal_config.json(gen_signal_config.py 校准)：每标的的 rsi_s/rsi_b(RSI<校准阈值) +
boll_s/boll_b(破 N日布林下轨)。个股率在悬浮卡片里显示该标的自己的历史成功率(如实带样本数 N)。
N 小(甚至=1)也保留——极罕见=极端，可靠性由 N 自证、不冒充 edge。
值为 [N, 5日, 10日, 20日 上涨率%]（同一批信号看不同持有期→反弹节奏；N=0 存 [0,null,null,null]）。
另存 _y=数据起始年(新股不足4.5年时)，供"自YYYY年回溯"文案。

重跑：python build_ticker_stats.py（先跑 gen_signal_config.py 生成 signal_config.json）
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "output" / "model_dataset.csv"
CFG = json.loads((ROOT / "signal_config.json").read_text(encoding="utf-8"))


def main():
    d = pd.read_csv(DATA).sort_values(["ticker", "date"]).reset_index(drop=True)
    # 先在完整连续序列上算 5/10/20 日前瞻收益(必须过滤前算，否则 shift 会跨越被删的末尾行)
    for h in (5, 10, 20):
        d[f"fwd{h}"] = d.groupby("ticker")["close"].shift(-h) / d["close"] - 1
    d["dt"] = pd.to_datetime(d["date"])
    # 两套用到的所有布林周期一次性算好
    periods = {c[w]["boll"][k] for c in CFG.values() for w in ("5y", "2y") for k in ("s", "b") if c[w]["boll"][k]}
    for N in periods:
        ma = d.groupby("ticker")["close"].transform(lambda s: s.rolling(N).mean())
        sd = d.groupby("ticker")["close"].transform(lambda s: s.rolling(N).std())
        d[f"boll{N}"] = d.close <= ma - 2 * sd
    d = d[d["fwd20"].notna()].copy()
    now = pd.Timestamp.today()
    cutoff = now - pd.DateOffset(years=2)

    def stat(gsub, mask):
        s = gsub[mask.reindex(gsub.index).fillna(False)]
        n = len(s)
        if not n:
            return [0, None, None, None]
        return [n] + [round((s[f"fwd{h}"] > 0).mean() * 100) for h in (5, 10, 20)]

    def slot_stats(gsub, cfg_win):
        e = {}
        if cfg_win["rsi"]["s"]:
            e["rsi_s"] = stat(gsub, gsub.rsi14 < cfg_win["rsi"]["s"])
        if cfg_win["rsi"]["b"]:
            e["rsi_b"] = stat(gsub, gsub.rsi14 < cfg_win["rsi"]["b"])
        for kind, key in (("boll_s", "s"), ("boll_b", "b")):
            if cfg_win["boll"][key]:
                e[kind] = stat(gsub, gsub[f"boll{cfg_win['boll'][key]}"])
        return e

    out = {}
    for tk, cfg in CFG.items():
        g = d[d.ticker == tk]
        if g.empty:
            continue
        g2 = g[g["dt"] >= cutoff]
        e5 = slot_stats(g, cfg["5y"])
        start = pd.to_datetime(g["date"].min())
        e5["_y"] = int(start.year) if (now - start).days / 365.25 < 4.5 else None
        out[tk] = {"5y": e5, "2y": slot_stats(g2, cfg["2y"])}   # 5年套用全样本、2年套用近两年样本

    if len(out) < 20:   # 正常应约 26 个；不足说明上游数据残缺，拒绝写表以免覆盖好数据
        raise SystemExit(f"❌ 只有 {len(out)} 个标的的统计，数据不完整，中止(不写 ticker_stats.js)")

    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output" / "ticker_stats.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    compact = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    (ROOT / "ticker_stats.js").write_text(f"window.TICKER_STATS={compact};\n", encoding="utf-8")
    print(f"共 {len(out)} 标的 → ticker_stats.js(工具) + output/ticker_stats.json")


if __name__ == "__main__":
    raise SystemExit(main())
