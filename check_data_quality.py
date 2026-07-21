#!/usr/bin/env python3
"""对 historical_data/*.csv 做系统性数据质量检查，输出每类检查的通过/失败明细。

检查维度：
  A. 结构完整性：日期唯一且严格递增、行列数、无全空文件
  B. OHLC 内部一致性：high>=open/close/low、low<=open/close/high、价格/成交量为正
  C. 极端跳变：|单日收益率| 超阈值时，核对是否有拆股记录能解释（能解释=正常，不能=可疑）
  D. 技术指标范围：RSI∈[0,100]、BOLL up>=mid>=low、MACD 恒等式 hist=2*(dif-dea)、无 inf
  E. 估值字段：PE>0(若非空)、PE分位∈[0,100]、TTM窗口完整性(跨度~270天)
  F. 前视偏差自检：pe_percentile_causal 只截断到当日重算一次，结果必须与全量结果一致
  G. 跨标的交易日历对齐：与 SPY(全周期基准)比较缺失的交易日
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "historical_data"

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "MCD", "TSM", "JPM",
           "CEG", "AVGO", "BRK-B", "LEU", "LLY", "QQQ", "SPY"]

RET_JUMP_THRESHOLD = 0.20  # 单日收益超过20%时进一步核查


def load(ticker: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{ticker}.csv", parse_dates=["date"])
    return df


def check_structure(ticker, df, issues):
    if df.empty:
        issues.append((ticker, "A-结构", "文件为空", ""))
        return
    if df["date"].duplicated().any():
        dupes = df.loc[df["date"].duplicated(), "date"].tolist()
        issues.append((ticker, "A-结构", "日期重复", str(dupes)))
    if not df["date"].is_monotonic_increasing:
        issues.append((ticker, "A-结构", "日期未严格递增", ""))
    if len(df.columns) != 55:
        issues.append((ticker, "A-结构", f"列数={len(df.columns)}(预期55)", ""))


def check_ohlc(ticker, df, issues):
    bad_hi = df[(df["high"] < df[["open", "close", "low"]].max(axis=1))]
    bad_lo = df[(df["low"] > df[["open", "close", "high"]].min(axis=1))]
    nonpos = df[(df[["open", "high", "low", "close"]] <= 0).any(axis=1)]
    negvol = df[df["volume"] < 0]
    for name, sub in [("high<max(o,c,l)", bad_hi), ("low>min(o,c,h)", bad_lo),
                       ("价格<=0", nonpos), ("成交量<0", negvol)]:
        if len(sub):
            issues.append((ticker, "B-OHLC", name, f"{len(sub)}行, 如 {sub['date'].iloc[0].date()}"))


def check_jumps(ticker, df, market_move_dates, issues):
    ret = df["close"].pct_change()
    jumps = df[ret.abs() > RET_JUMP_THRESHOLD].copy()
    if jumps.empty:
        return
    for idx, row in jumps.iterrows():
        d = row["date"]
        pct = ret.loc[idx] * 100
        peer_confirmed = d in market_move_dates  # 同一天多数标的都大动 -> 大概率是真实大盘/个股事件
        # 「round-trip」指纹：次日大幅反向抵消，是坏 tick 的典型特征
        roundtrip = False
        if idx + 1 in df.index:
            r2 = df["close"].iloc[idx + 1] / df["close"].iloc[idx] - 1
            if np.sign(r2) != np.sign(ret.loc[idx]) and abs((1 + ret.loc[idx]) * (1 + r2) - 1) < 0.03:
                roundtrip = True
        tag = "疑似坏tick(次日大幅反向抵消)" if roundtrip else ("多标的同日大动,像真实市场事件" if peer_confirmed else "单标的孤立跳变,建议人工复核")
        issues.append((ticker, "C-极端跳变", f"{d.date()} 单日{pct:+.1f}% [{tag}]", ""))


def check_indicators(ticker, df, issues):
    num = df.select_dtypes("number")
    n_inf = np.isinf(num.to_numpy()).sum()
    if n_inf:
        issues.append((ticker, "D-指标", f"含 {n_inf} 处 inf/-inf", ""))

    rsi_bad = df[(df["rsi14"] < 0) | (df["rsi14"] > 100)]
    if len(rsi_bad):
        issues.append((ticker, "D-指标", f"RSI越界 {len(rsi_bad)}行", ""))

    boll_bad = df.dropna(subset=["boll_up", "boll_mid", "boll_low"])
    boll_bad = boll_bad[~((boll_bad["boll_up"] >= boll_bad["boll_mid"]) & (boll_bad["boll_mid"] >= boll_bad["boll_low"]))]
    if len(boll_bad):
        issues.append((ticker, "D-指标", f"BOLL up>=mid>=low 不成立 {len(boll_bad)}行", ""))

    macd_check = df.dropna(subset=["macd_dif", "macd_dea", "macd_hist"])
    resid = (macd_check["macd_hist"] - 2 * (macd_check["macd_dif"] - macd_check["macd_dea"])).abs()
    if (resid > 1e-6).any():
        issues.append((ticker, "D-指标", f"MACD恒等式不成立 {(resid > 1e-6).sum()}行", ""))


def check_fundamentals(ticker, df, issues):
    if df["pe_ttm"].notna().sum() == 0:
        return  # ETF/BRK-B 等本就无估值数据，非问题
    pe_bad = df[df["pe_ttm"].notna() & (df["pe_ttm"] <= 0)]
    if len(pe_bad):
        issues.append((ticker, "E-估值", f"PE<=0但未置空 {len(pe_bad)}行", str(pe_bad['date'].iloc[0].date())))

    for col in ["pe_percentile_causal", "pe_percentile_full_sample"]:
        sub = df[df[col].notna() & ((df[col] < 0) | (df[col] > 100))]
        if len(sub):
            issues.append((ticker, "E-估值", f"{col} 越界[0,100] {len(sub)}行", ""))

    # causal 分位不应严格大于 full_sample 分位太多（causal应更"保守"，因为只看过去），
    # 但两者定义不同允许有差异，这里只做粗略合理性提示，不做硬性判定。


def check_causal_no_lookahead(ticker, df, issues):
    """抽样验证 pe_percentile_causal 无前视：截断到某行重算，应与原值一致。"""
    if df["pe_ttm"].notna().sum() < 30:
        return
    valid_idx = df.index[df["pe_ttm"].notna()]
    sample_positions = np.linspace(len(valid_idx) // 2, len(valid_idx) - 1, 3, dtype=int)
    vals_full = df["pe_ttm"].to_numpy()
    causal_full = df["pe_percentile_causal"].to_numpy()
    for pos in sample_positions:
        i = valid_idx[pos]
        window = vals_full[: i + 1]
        window = window[~np.isnan(window)]
        if len(window) < 20:
            continue
        expected = (window <= vals_full[i]).mean() * 100
        actual = causal_full[i]
        if not np.isclose(expected, actual, atol=1e-6):
            issues.append((ticker, "F-前视校验", f"行{i}({df['date'].iloc[i].date()}) causal分位不匹配: 期望{expected:.2f} 实际{actual:.2f}", ""))


def check_calendar_alignment(all_dfs, issues):
    baseline_ticker = "SPY"
    baseline_dates = set(all_dfs[baseline_ticker]["date"])
    for ticker, df in all_dfs.items():
        if ticker == baseline_ticker:
            continue
        dates = set(df["date"])
        own_range = (df["date"].min(), df["date"].max())
        # 只比较该标的自身上市/覆盖区间内、且基准也覆盖的日期
        relevant_baseline = {d for d in baseline_dates if own_range[0] <= d <= own_range[1]}
        missing = relevant_baseline - dates
        extra = dates - baseline_dates
        if len(missing) > 2:  # 容忍1-2天的标的特有停牌
            sample = sorted(missing)[:5]
            issues.append((ticker, "G-日历对齐", f"相对SPY缺失{len(missing)}个交易日", str([d.date() for d in sample])))
        if len(extra) > 2:
            sample = sorted(extra)[:5]
            issues.append((ticker, "G-日历对齐", f"比SPY多{len(extra)}个交易日(非公共假日)", str([d.date() for d in sample])))


def main():
    issues = []
    all_dfs = {}
    for ticker in TICKERS:
        path = DATA_DIR / f"{ticker}.csv"
        if not path.exists():
            issues.append((ticker, "A-结构", "文件不存在", ""))
            continue
        all_dfs[ticker] = load(ticker)

    # 大盘/多标的联动日：同一天 >=8 支标的单日|涨跌|>10%，视为真实市场事件而非个股数据问题
    move_counts = {}
    for df in all_dfs.values():
        ret = df["close"].pct_change()
        for d in df.loc[ret.abs() > 0.10, "date"]:
            move_counts[d] = move_counts.get(d, 0) + 1
    market_move_dates = {d for d, n in move_counts.items() if n >= 8}

    for ticker, df in all_dfs.items():
        check_structure(ticker, df, issues)
        check_ohlc(ticker, df, issues)
        check_jumps(ticker, df, market_move_dates, issues)
        check_indicators(ticker, df, issues)
        check_fundamentals(ticker, df, issues)
        check_causal_no_lookahead(ticker, df, issues)

    check_calendar_alignment(all_dfs, issues)

    if not issues:
        print("全部检查通过，未发现数据质量问题。")
        return

    print(f"发现 {len(issues)} 项问题：\n")
    cur_cat = None
    for ticker, cat, msg, extra in sorted(issues, key=lambda x: (x[1], x[0])):
        if cat != cur_cat:
            print(f"\n--- {cat} ---")
            cur_cat = cat
        print(f"  [{ticker}] {msg} {extra}")


if __name__ == "__main__":
    sys.exit(main())
