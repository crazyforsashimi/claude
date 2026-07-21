#!/usr/bin/env python3
"""在 historical_data/ 的干净日线数据上，构建「建模就绪」数据集 model_dataset.csv。

产出两样东西（供 LightGBM/XGBoost 训练买入/卖出高精度信号）：

1) 三重障碍标签（Triple Barrier，López de Prado）——绝对收益口径，参数 3/2/20：
     买入(long)：  上障碍 = entry + 3×ATR14  (止盈/成功)
                   下障碍 = entry − 2×ATR14  (止损/失败)
     卖出(short)： 下障碍 = entry − 3×ATR14  (止盈/成功)
                   上障碍 = entry + 2×ATR14  (止损/失败)
     时间障碍：    未来 20 个交易日；到期未触及 = 中性
   entry = 当日收盘价；ATR 在 entry 时刻固定。持有期内生浮动（谁先碰到谁结算），
   不依赖某个固定日期——这正是三重障碍相对「死盯第 N 日收盘」的优势。
   标签做成二分类 tb_long/tb_short ∈ {0,1}（1=止盈先于止损触及=大机会成功），
   精度(precision)即「打了买入/卖出标签里实际成功的比例」，正对用户「宁缺毋滥、要准」的诉求。

   保守假设（日线无盘中路径）：同一日 high、low 同时越过上下障碍时，一律判「失败方向先到」
   （止损优先），不夸大胜率。止盈/止损成交价按障碍价计，未建模跳空滑点（偏保守）。

2) 派生特征——现有列里没有、但对「大机会」判别有用，全部 causal（只用当日及之前数据）：
     dist_52w_high  距52周高点距离      px_ma20/50/200  价相对均线
     ma20_ma50/ma50_ma200 均线排列       above_ma200     趋势过滤
     macd_hist_norm 归一化MACD柱         atr_pct/boll_bw 波动率/带宽
     obv_z          OBV标准分            excess_ret20_spy/qqq 相对大盘超额动量
     vol20_pctile   波动率历史分位(扩张窗口)  log_mktcap  规模

前视偏差控制：黑名单列（fwd_ret_*、tb_* 标签、pe_percentile_full_sample、以及所有价格绝对水平列）
一律不进 FEATURE_COLS 白名单。基本面列允许 NaN（树模型原生处理），只要技术面核心特征齐全即可训练。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "historical_data"
OUT_PATH = ROOT / "output" / "model_dataset.csv"

HORIZON = 20        # 时间障碍：交易日
UP_MULT_LONG, DOWN_MULT_LONG = 3.0, 2.0     # 买入：止盈 +3ATR / 止损 −2ATR
UP_MULT_SHORT, DOWN_MULT_SHORT = 2.0, 3.0   # 卖出：止损 +2ATR / 止盈 −3ATR

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "MCD", "TSM",
           "JPM", "CEG", "AVGO", "BRK-B", "LEU", "LLY",
           "AMD", "MU", "QCOM", "NET", "SNOW", "VST", "NEE", "GEV", "CAT", "COIN",
           "BABA", "GS", "MS", "SOXX",
           "QQQ", "SPY"]

# ---- 特征白名单：只含无量纲/相对/有界的列，跨标的可比，无前视偏差 ----
# 技术面核心（要求非空才算 trainable）：
CORE_FEATURES = [
    "ret_1d", "ret_5d", "ret_20d", "ret_60d", "ret_252d",
    "vol_20d_ann", "vol_60d_ann", "vol20_pctile", "atr_pct", "boll_bw",
    "rsi14", "kdj_k", "kdj_d", "kdj_j", "cci20", "willr14", "mfi14", "boll_pctb",
    "vol_ratio", "obv_z",
    "px_ma20", "px_ma50", "px_ma200", "ma20_ma50", "ma50_ma200", "above_ma200",
    "dist_52w_high", "macd_hist_norm",
    "excess_ret20_spy", "excess_ret20_qqq",
]
# 基本面（允许 NaN，LightGBM 原生处理缺失；ETF/BRK-B 会是空）：
FUND_FEATURES = [
    "pe_percentile_causal", "pb", "ps_ttm", "roe_ttm",
    "gross_margin_ttm", "operating_margin_ttm", "leverage_ratio", "log_mktcap",
]
FEATURE_COLS = CORE_FEATURES + FUND_FEATURES

# 明确禁止当特征（写进文档，防误用）：
BLACKLIST = [
    "date", "open", "high", "low", "close", "vwap", "transactions", "volume",
    "ma5", "ma10", "ma20", "ma50", "ma100", "ma200", "ema12", "ema26",
    "macd_dif", "macd_dea", "macd_hist", "boll_mid", "boll_up", "boll_low",
    "atr14", "obv", "vol_ma20", "eps_ttm", "pe_ttm", "market_cap_approx",
    "pe_percentile_full_sample",                      # 前视偏差（全样本分位）
    "fwd_ret_1d", "fwd_ret_5d", "fwd_ret_20d",        # 旧前瞻收益标签
    "tb_long", "tb_short", "tb_long_touch", "tb_long_ret", "tb_long_days",
    "tb_short_touch", "tb_short_ret", "tb_short_days",  # 三重障碍标签及其辅助列
]


def causal_percentile(s: pd.Series, min_obs: int = 60) -> pd.Series:
    """扩张窗口分位：第 i 个值在「截至 i 为止的历史」里的百分位（0-100），避免前视偏差。"""
    vals = s.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if np.isnan(vals[i]):
            continue
        window = vals[: i + 1]
        window = window[~np.isnan(window)]
        if len(window) >= min_obs:
            out[i] = (window <= vals[i]).mean() * 100
    return pd.Series(out, index=s.index)


def triple_barrier(df: pd.DataFrame, up_mult: float, down_mult: float,
                   success_side: str, horizon: int):
    """通用三重障碍。success_side='up' 为买入视角，'down' 为卖出视角。

    返回 (label, touch, strat_ret, days)：
      label ∈ {0,1}：1=止盈障碍(成功方向)先于止损障碍触及；0=止损先到 或 到期未触及
      touch ∈ {'up','down','time',None}：实际先触及哪条障碍（None=窗口不满，无法定论）
      strat_ret：策略视角对数收益（成功为正）——买入=价格收益，卖出=价格收益取负
      days：从 entry 到结算用了几个交易日
    """
    c = df["close"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    a = df["atr14"].to_numpy(dtype=float)
    n = len(c)
    label = np.full(n, np.nan)
    touch = np.array([None] * n, dtype=object)
    strat_ret = np.full(n, np.nan)
    days = np.full(n, np.nan)

    for t in range(n):
        entry, atr_t = c[t], a[t]
        if np.isnan(entry) or np.isnan(atr_t) or atr_t <= 0 or t + 1 >= n:
            continue
        up = entry + up_mult * atr_t
        dn = entry - down_mult * atr_t
        end = min(t + horizon, n - 1)
        outcome = None
        for k in range(t + 1, end + 1):
            hit_up, hit_dn = h[k] >= up, l[k] <= dn
            if hit_up and hit_dn:                 # 双触：保守判失败方向（止损优先）
                outcome = ("down" if success_side == "up" else "up", k)
                break
            if hit_up:
                outcome = ("up", k)
                break
            if hit_dn:
                outcome = ("down", k)
                break

        if outcome is None:
            if end - t < horizon:                 # 接近数据末尾，窗口不满 → 无法定论
                continue
            label[t], touch[t], days[t] = 0, "time", end - t   # 时间障碍=中性→并入0类
            pr = np.log(c[end] / entry)
        else:
            side, k = outcome
            touch[t], days[t] = side, k - t
            label[t] = 1 if side == success_side else 0
            barrier = up if side == "up" else dn
            pr = np.log(barrier / entry)
        strat_ret[t] = pr if success_side == "up" else -pr

    return label, touch, strat_ret, days


def add_derived_features(df: pd.DataFrame, bench: dict) -> pd.DataFrame:
    close, high = df["close"], df["high"]
    df["dist_52w_high"] = close / high.rolling(252, min_periods=200).max() - 1
    df["px_ma20"] = close / df["ma20"] - 1
    df["px_ma50"] = close / df["ma50"] - 1
    df["px_ma200"] = close / df["ma200"] - 1
    df["ma20_ma50"] = df["ma20"] / df["ma50"] - 1
    df["ma50_ma200"] = df["ma50"] / df["ma200"] - 1
    df["above_ma200"] = (close > df["ma200"]).astype(float)
    df["macd_hist_norm"] = df["macd_hist"] / close
    df["atr_pct"] = df["atr14"] / close
    df["boll_bw"] = (df["boll_up"] - df["boll_low"]) / df["boll_mid"]
    obv = df["obv"]
    df["obv_z"] = (obv - obv.rolling(20).mean()) / obv.rolling(20).std(ddof=0)
    df["vol20_pctile"] = causal_percentile(df["vol_20d_ann"])
    mc = df["market_cap_approx"]
    with np.errstate(invalid="ignore", divide="ignore"):   # ETF/缺失市值 → NaN，预期内
        df["log_mktcap"] = np.log(mc.where(mc > 0))

    d = df["date"].astype(str)
    df["excess_ret20_spy"] = df["ret_20d"] - d.map(bench["SPY"])
    df["excess_ret20_qqq"] = df["ret_20d"] - d.map(bench["QQQ"])
    return df


def load_benchmark(name: str) -> dict:
    b = pd.read_csv(DATA_DIR / f"{name}.csv", usecols=["date", "ret_20d"])
    return dict(zip(b["date"].astype(str), b["ret_20d"]))


def main():
    bench = {"SPY": load_benchmark("SPY"), "QQQ": load_benchmark("QQQ")}
    frames, summary = [], []

    for tk in TICKERS:
        path = DATA_DIR / f"{tk}.csv"
        if not path.exists():
            print(f"[跳过] {tk}: 文件不存在")
            continue
        df = pd.read_csv(path)
        df = add_derived_features(df, bench)

        lb, lt, lr, ld = triple_barrier(df, UP_MULT_LONG, DOWN_MULT_LONG, "up", HORIZON)
        sb, st, sr, sd = triple_barrier(df, UP_MULT_SHORT, DOWN_MULT_SHORT, "down", HORIZON)
        df["tb_long"], df["tb_long_touch"], df["tb_long_ret"], df["tb_long_days"] = lb, lt, lr, ld
        df["tb_short"], df["tb_short_touch"], df["tb_short_ret"], df["tb_short_days"] = sb, st, sr, sd

        core_ok = df[CORE_FEATURES].notna().all(axis=1)
        df["trainable_long"] = core_ok & df["tb_long"].notna()
        df["trainable_short"] = core_ok & df["tb_short"].notna()
        df.insert(0, "ticker", tk)
        frames.append(df)

        tl = df.loc[df["trainable_long"], "tb_long"]
        ts = df.loc[df["trainable_short"], "tb_short"]
        summary.append((tk, len(df), int(df["trainable_long"].sum()),
                        tl.mean() if len(tl) else np.nan,
                        ts.mean() if len(ts) else np.nan))

    full = pd.concat(frames, ignore_index=True)
    OUT_PATH.parent.mkdir(exist_ok=True)
    full.to_csv(OUT_PATH, index=False)

    print(f"\n输出: {OUT_PATH.name}  共 {len(full)} 行 × {full.shape[1]} 列")
    print(f"特征白名单: {len(FEATURE_COLS)} 列（核心技术面 {len(CORE_FEATURES)} + 基本面 {len(FUND_FEATURES)}）\n")
    print(f"{'标的':<7}{'总行':>6}{'可训练':>8}{'买入正样本率':>14}{'卖出正样本率':>14}")
    for tk, nrow, ntr, lp, sp in summary:
        lp_s = f"{lp:.1%}" if not np.isnan(lp) else "—"
        sp_s = f"{sp:.1%}" if not np.isnan(sp) else "—"
        print(f"{tk:<7}{nrow:>6}{ntr:>8}{lp_s:>14}{sp_s:>14}")

    tr_l = full[full["trainable_long"]]
    tr_s = full[full["trainable_short"]]
    print(f"\n合计可训练(买入): {len(tr_l)} 行，基准正样本率 {tr_l['tb_long'].mean():.1%}"
          f"  → 随机打标签精度≈此值，模型要顶到 70% 才算有 alpha")
    print(f"合计可训练(卖出): {len(tr_s)} 行，基准正样本率 {tr_s['tb_short'].mean():.1%}")
    print(f"\n买入触及分布: {full['tb_long_touch'].value_counts().to_dict()}")
    print(f"卖出触及分布: {full['tb_short_touch'].value_counts().to_dict()}")


if __name__ == "__main__":
    sys.exit(main())
