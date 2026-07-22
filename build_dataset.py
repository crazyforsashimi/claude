#!/usr/bin/env python3
"""构建用于算法建模的多因子日线数据集。

对 stock-screener 的 17 支自选标的，输出 历史data/{TICKER}.csv，每行=一个交易日，列包括：
  - 原始OHLCV
  - 技术面指标：MA/EMA/MACD/RSI(14,Wilder)/KDJ(9,3,3)/BOLL(20,2)/ATR/CCI/威廉%R/OBV/MFI/量比/多周期收益率&波动率
    (RSI/MACD/KDJ/BOLL 公式与 index.html 完全一致，已与 Polygon 官方指标端点交叉验证)
  - 估值/基本面：PE_TTM、PE分位(两种口径见下)、PB、PS_TTM、ROE_TTM、毛利率/营业利润率TTM、杠杆率、近似市值
    (按财报 filing_date 前推到每个交易日，避免未来数据泄露；EPS/股数按拆股比例换算到当前股本口径)
  - 前瞻收益率标签 fwd_ret_*（监督学习的 y，故意使用未来数据，仅最后N行为空属预期行为）

数据源：Massive/Polygon REST，Starter 档（5年历史、24季度财报）。
ETF(QQQ/SPY) 不申报财报 -> 估值列留空，不冒充。

PE分位说明（避免误用造成前视偏差 look-ahead bias）：
  - pe_percentile_causal：截至当日为止的"扩张窗口"分位 —— 可放心用作 ML 特征。
  - pe_percentile_full_sample：用全部5年样本计算的分位（与 index.html 实时工具口径一致，
    但对样本早期的行而言用到了"未来"数据）—— 仅用于核对/展示，不要用作训练特征。
"""
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).parent
CONFIG_JS = ROOT / "config.js"
OUT_DIR = ROOT / "historical_data"
BASE = "https://api.polygon.io"

# (ticker, is_etf) —— 与 index.html 的 UNIVERSE 保持一致
UNIVERSE = [
    ("AAPL", False), ("MSFT", False), ("GOOGL", False), ("AMZN", False), ("NVDA", False),
    ("META", False), ("TSLA", False), ("MCD", False), ("TSM", False), ("JPM", False),
    ("CEG", False), ("AVGO", False), ("BRK.B", False), ("LEU", False), ("LLY", False),
    # v12 扩池(+14)：半导体/软件/电力/工业/加密/中概/金融。GEV(2024上市)历史仅~2年，回溯样本有限
    ("AMD", False), ("MU", False), ("QCOM", False), ("NET", False), ("SNOW", False),
    ("VST", False), ("NEE", False), ("GEV", False), ("CAT", False), ("COIN", False),
    ("BABA", False), ("GS", False), ("MS", False),
    ("QQQ", True), ("SPY", True), ("SOXX", True),
]

YEARS_BACK = 5
STALE_DAYS = 200   # 财报陈旧度上限(交易日距所用财报的公布日)。超过=中间有季度缺失(如银行Q4并入年报、
                   # Polygon 漏季)导致 merge_asof 回退到过旧财报、TTM 滞后失真 → 该行估值全部置缺失，不冒充


def load_api_key() -> str:
    k = os.environ.get("MASSIVE_API_KEY")     # 云端 Action 用 Secrets；本地 fallback config.js
    if k:
        return k
    text = CONFIG_JS.read_text(encoding="utf-8")
    m = re.search(r'MASSIVE_API_KEY\s*=\s*"([^"]+)"', text)
    if not m:
        raise RuntimeError(f"未能在 {CONFIG_JS} 中找到 MASSIVE_API_KEY")
    return m.group(1)


def api_get(path: str, params: dict) -> dict:
    resp = requests.get(f"{BASE}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------- 数据抓取

def fetch_daily_bars(ticker: str, api_key: str, start: str, end: str) -> pd.DataFrame:
    url = f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key}
    rows = []
    while url:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("results", []))
        next_url = data.get("next_url")
        url, params = (next_url, {"apiKey": api_key}) if next_url else (None, None)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["t"], unit="ms").dt.date
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close",
                             "v": "volume", "vw": "vwap", "n": "transactions"})
    return df[["date", "open", "high", "low", "close", "volume", "vwap", "transactions"]].sort_values("date").reset_index(drop=True)


def drop_unreliable_price_regime(ticker: str, df: pd.DataFrame, splits: list[tuple]) -> pd.DataFrame:
    """探测"交易日历大缺口 + 缺口前后价格跳变且无拆股解释"的供应商数据错误段，丢弃缺口之前的数据。

    典型案例：META 2021-07~2022-01 期间 Polygon 返回的收盘价系统性错误(~$12-15，
    真实值应~$300+)，随后 2022-01~2022-06 又缺失约90个交易日，2022-06-09起恢复正常。
    与其在这段用错误值参与指标/财报计算，不如整体丢弃，让下游明确"数据从此日期才可靠"。
    """
    dates = pd.to_datetime(df["date"])
    gap_days = dates.diff().dt.days
    GAP_THRESHOLD_DAYS = 10  # 正常周末/假期最多3-4天，超过10天视为异常缺口
    gap_positions = np.where(gap_days > GAP_THRESHOLD_DAYS)[0]
    if len(gap_positions) == 0:
        return df

    split_dates = {pd.Timestamp(d) for d, _ in splits}
    cut_at = None
    for pos in gap_positions:
        before, after = df["close"].iloc[pos - 1], df["close"].iloc[pos]
        ratio = after / before
        gap_start, gap_end = dates.iloc[pos - 1], dates.iloc[pos]
        has_split_in_gap = any(gap_start < d <= gap_end for d in split_dates)
        if not has_split_in_gap and (ratio > 3 or ratio < 1 / 3):
            cut_at = pos  # 保留缺口之后(含)的数据，丢弃之前
    if cut_at is not None:
        dropped_range = (df["date"].iloc[0], df["date"].iloc[cut_at - 1])
        print(f"  [数据修复] {ticker}: 检测到无拆股解释的价格跳变+日历缺口，"
              f"丢弃 {dropped_range[0]}~{dropped_range[1]} 共{cut_at}行不可靠数据")
        return df.iloc[cut_at:].reset_index(drop=True)
    return df


def fetch_quarterly_financials(ticker: str, api_key: str) -> list[dict]:
    results, cursor = [], None
    for _ in range(6):  # 每页最多100条，6页足够覆盖5年+缓冲
        params = {"ticker": ticker, "timeframe": "quarterly", "limit": 100,
                   "sort": "period_of_report_date", "order": "asc", "apiKey": api_key}
        if cursor:
            params = {"cursor": cursor, "apiKey": api_key}
        data = api_get("/vX/reference/financials", params)
        results.extend(data.get("results", []))
        next_url = (data.get("next_url") or "")
        m = re.search(r"cursor=([^&]+)", next_url)
        if not m:
            break
        cursor = m.group(1)
    return results


def fetch_splits(ticker: str, api_key: str) -> list[tuple]:
    data = api_get("/stocks/v1/splits", {"ticker": ticker, "limit": 100, "apiKey": api_key})
    rows = data.get("results", [])
    out = [(r["execution_date"], r["historical_adjustment_factor"]) for r in rows]
    return sorted(out)


def split_factor_for(quarter_end: str, splits_sorted: list[tuple]) -> float:
    """quarter_end 之后第一次拆股事件的累计调整因子(已含其后所有拆股)；无则1.0。"""
    for exec_date, factor in splits_sorted:
        if exec_date > quarter_end:
            return factor
    return 1.0


# ---------------------------------------------------------------- 基本面 -> 逐日序列

def fget(fin: dict, *path):
    node = fin.get("financials", {})
    for key in path[:-1]:
        node = node.get(key, {})
    return node.get(path[-1], {}).get("value")


def build_fundamentals_daily(financials: list[dict], splits: list[tuple]) -> pd.DataFrame:
    recs = []
    for f in sorted(financials, key=lambda x: x["end_date"]):
        eps = fget(f, "income_statement", "diluted_earnings_per_share")
        shares = fget(f, "income_statement", "diluted_average_shares")
        if eps is None or shares is None:
            continue
        factor = split_factor_for(f["end_date"], splits)
        recs.append({
            "end_date": f["end_date"],
            "known_date": f.get("filing_date") or f.get("acceptance_datetime", "")[:10] or f["end_date"],
            "eps_adj": eps * factor,
            "shares_adj": shares / factor,
            "revenue": fget(f, "income_statement", "revenues"),
            "gross_profit": fget(f, "income_statement", "gross_profit"),
            "operating_income": fget(f, "income_statement", "operating_income_loss"),
            "net_income": (fget(f, "income_statement", "net_income_loss_attributable_to_parent")
                           or fget(f, "income_statement", "net_income_loss")),
            "equity": (fget(f, "balance_sheet", "equity_attributable_to_parent")
                       or fget(f, "balance_sheet", "equity")),
            "liabilities": fget(f, "balance_sheet", "liabilities"),
        })
    if len(recs) < 4:
        return pd.DataFrame()

    fdf = pd.DataFrame(recs).sort_values("end_date").reset_index(drop=True)
    # filing_date 缺失时(最新一季常见)用 end_date+50天 近似申报滞后，避免用尚未公开的数据
    known = pd.to_datetime(fdf["known_date"], errors="coerce")
    fallback = pd.to_datetime(fdf["end_date"]) + pd.Timedelta(days=50)
    fdf["known_date"] = known.fillna(fallback)

    for col in ["eps_adj", "revenue", "gross_profit", "operating_income", "net_income"]:
        fdf[col + "_ttm"] = fdf[col].rolling(4).sum()

    # 数据源偶发漏收某季度(如 META 缺 2022Q4)时，trailing-4 会静默跨用错的季度拼出"12个月"，
    # 拼出的TTM实际不对齐日历年 -> 用首尾 end_date 跨度做完整性校验(健康值约270天=3个季度间隔)，
    # 跨度异常(如缺一季导致跨度~365天)则判定TTM不可信，整行置缺失，不冒充。
    end_dates = pd.to_datetime(fdf["end_date"])
    span_days = (end_dates - end_dates.shift(3)).dt.days
    bad = (span_days < 200) | (span_days > 320)
    ttm_cols = [c + "_ttm" for c in ["eps_adj", "revenue", "gross_profit", "operating_income", "net_income"]]
    fdf.loc[bad.fillna(True), ttm_cols] = np.nan

    fdf = fdf.dropna(subset=["eps_adj_ttm"]).reset_index(drop=True)
    return fdf[["known_date", "eps_adj_ttm", "revenue_ttm", "gross_profit_ttm", "operating_income_ttm",
                "net_income_ttm", "equity", "liabilities", "shares_adj"]]


# ---------------------------------------------------------------- 技术指标 (与 index.html 同公式)

def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    c = close.to_numpy()
    out = np.full(len(c), np.nan)
    if len(c) < period + 1:
        return pd.Series(out, index=close.index)
    diffs = np.diff(c)
    g = diffs[:period].clip(min=0).mean()
    l = (-diffs[:period]).clip(min=0).mean()
    out[period] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(period, len(diffs)):
        d = diffs[i]
        g = (g * (period - 1) + max(d, 0)) / period
        l = (l * (period - 1) + max(-d, 0)) / period
        out[i + 1] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return pd.Series(out, index=close.index)


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9):
    h, l, c = high.to_numpy(), low.to_numpy(), close.to_numpy()
    K = np.full(len(c), np.nan)
    D = np.full(len(c), np.nan)
    k, d = 50.0, 50.0
    for i in range(len(c)):
        s = max(0, i - n + 1)
        hh, ll = h[s:i + 1].max(), l[s:i + 1].min()
        rsv = (c[i] - ll) / (hh - ll) * 100 if hh > ll else 0
        k = 2 / 3 * k + 1 / 3 * rsv
        d = 2 / 3 * d + 1 / 3 * k
        K[i], D[i] = k, d
    j = 3 * K - 2 * D
    return pd.Series(K, index=close.index), pd.Series(D, index=close.index), pd.Series(j, index=close.index)


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    for n in (1, 5, 20, 60, 252):
        df[f"ret_{n}d"] = np.log(c / c.shift(n))
    for n in (20, 60):
        df[f"vol_{n}d_ann"] = df["ret_1d"].rolling(n).std() * np.sqrt(252)

    for n in (5, 10, 20, 50, 100, 200):
        df[f"ma{n}"] = c.rolling(n).mean()

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    df["ema12"], df["ema26"] = ema12, ema26
    df["macd_dif"], df["macd_dea"], df["macd_hist"] = dif, dea, 2 * (dif - dea)

    df["rsi14"] = wilder_rsi(c, 14)
    df["kdj_k"], df["kdj_d"], df["kdj_j"] = kdj(h, l, c, 9)

    mid = c.rolling(20).mean()
    std = c.rolling(20).std(ddof=0)
    df["boll_mid"], df["boll_up"], df["boll_low"] = mid, mid + 2 * std, mid - 2 * std
    df["boll_pctb"] = (c - df["boll_low"]) / (df["boll_up"] - df["boll_low"]) * 100

    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    tp = (h + l + c) / 3
    sma_tp = tp.rolling(20).mean()
    mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["cci20"] = (tp - sma_tp) / (0.015 * mad)

    hh14, ll14 = h.rolling(14).max(), l.rolling(14).min()
    df["willr14"] = (hh14 - c) / (hh14 - ll14) * -100

    sign = np.sign(c.diff()).fillna(0)
    df["obv"] = (sign * v).cumsum()

    rmf = tp * v
    tp_diff = tp.diff()
    pos_mf = rmf.where(tp_diff > 0, 0).rolling(14).sum()
    neg_mf = rmf.where(tp_diff < 0, 0).rolling(14).sum()
    df["mfi14"] = 100 - 100 / (1 + pos_mf / neg_mf)

    df["vol_ma20"] = v.rolling(20).mean()
    df["vol_ratio"] = v / df["vol_ma20"]

    # 前瞻收益率标签（故意用未来数据，仅供监督学习当 y，不可用作特征）
    for n in (1, 5, 20):
        df[f"fwd_ret_{n}d"] = np.log(c.shift(-n) / c)

    return df


def add_fundamentals(df: pd.DataFrame, fdf: pd.DataFrame) -> pd.DataFrame:
    if fdf.empty:
        for col in ["pe_ttm", "eps_ttm", "pe_percentile_causal", "pe_percentile_full_sample",
                    "pb", "ps_ttm", "roe_ttm", "gross_margin_ttm", "operating_margin_ttm",
                    "leverage_ratio", "market_cap_approx"]:
            df[col] = np.nan
        return df

    left = df.copy()
    left["date_ts"] = pd.to_datetime(left["date"])
    fdf = fdf.sort_values("known_date")
    merged = pd.merge_asof(left.sort_values("date_ts"), fdf, left_on="date_ts", right_on="known_date", direction="backward")

    # 财报陈旧度过滤：某交易日用的财报公布日距该日 > STALE_DAYS，说明中间有季度缺失(Polygon 常缺银行
    # Q4/漏季)使 merge_asof 回退到过旧财报、TTM 滞后失真(如 JPM 缺 2024Q4 → 2025 全年 EPS 卡在旧值)。
    # 此时该行估值全部置缺失，绝不用滞后值冒充；PE 分位据此自动跳过这些坏点。
    stale = (merged["date_ts"] - pd.to_datetime(merged["known_date"])).dt.days > STALE_DAYS
    fund_cols = ["eps_adj_ttm", "net_income_ttm", "revenue_ttm", "gross_profit_ttm",
                 "operating_income_ttm", "equity", "liabilities", "shares_adj"]
    merged.loc[stale, fund_cols] = np.nan

    eps_ttm = merged["eps_adj_ttm"]
    net_income_ttm = merged["net_income_ttm"]
    shares = merged["shares_adj"]
    equity = merged["equity"]
    close = merged["close"]

    mktcap = close * shares
    pe_primary = close / eps_ttm
    pe_fallback = mktcap / net_income_ttm
    pe = pe_primary.where(eps_ttm > 0, pe_fallback.where(net_income_ttm > 0))

    merged["eps_ttm"] = eps_ttm
    merged["pe_ttm"] = pe
    merged["pb"] = close / (equity / shares)
    merged["ps_ttm"] = mktcap / merged["revenue_ttm"]
    merged["roe_ttm"] = net_income_ttm / equity
    merged["gross_margin_ttm"] = merged["gross_profit_ttm"] / merged["revenue_ttm"]
    merged["operating_margin_ttm"] = merged["operating_income_ttm"] / merged["revenue_ttm"]
    merged["leverage_ratio"] = merged["liabilities"] / equity
    merged["market_cap_approx"] = mktcap

    valid_pe = pe.copy()
    n = len(valid_pe)
    causal = np.full(n, np.nan)
    vals = valid_pe.to_numpy()
    for i in range(n):
        if np.isnan(vals[i]):
            continue
        window = vals[: i + 1]
        window = window[~np.isnan(window)]
        if len(window) >= 20:
            causal[i] = (window <= vals[i]).mean() * 100
    merged["pe_percentile_causal"] = causal

    full_valid = vals[~np.isnan(vals)]
    if len(full_valid) >= 20:
        merged["pe_percentile_full_sample"] = [
            np.nan if np.isnan(x) else (full_valid <= x).mean() * 100 for x in vals
        ]
    else:
        merged["pe_percentile_full_sample"] = np.nan

    keep = ["pe_ttm", "eps_ttm", "pe_percentile_causal", "pe_percentile_full_sample",
            "pb", "ps_ttm", "roe_ttm", "gross_margin_ttm", "operating_margin_ttm",
            "leverage_ratio", "market_cap_approx"]
    for col in keep:
        df[col] = merged[col].values
    return df


# ---------------------------------------------------------------- 主流程

def main():
    api_key = load_api_key()
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=YEARS_BACK)
    start_s, end_s = start.date().isoformat(), end.date().isoformat()

    OUT_DIR.mkdir(exist_ok=True)
    print(f"下载/计算区间: {start_s} ~ {end_s}\n输出目录: {OUT_DIR}\n")

    failed = []
    for ticker, is_etf in UNIVERSE:
        try:
            bars = fetch_daily_bars(ticker, api_key, start_s, end_s)
            if bars.empty:
                print(f"[跳过] {ticker}: 无价格数据")
                failed.append(ticker)
                continue

            splits = [] if is_etf else fetch_splits(ticker, api_key)
            bars = drop_unreliable_price_regime(ticker, bars, splits)
            df = add_technical_indicators(bars)

            if not is_etf:
                financials = fetch_quarterly_financials(ticker, api_key)
                fdf = build_fundamentals_daily(financials, splits)
                df = add_fundamentals(df, fdf)
            else:
                df = add_fundamentals(df, pd.DataFrame())

            safe_name = ticker.replace(".", "-")
            out_path = OUT_DIR / f"{safe_name}.csv"
            df.to_csv(out_path, index=False)
            print(f"[完成] {ticker}: {len(df)} 行 x {len(df.columns)} 列 -> {out_path.name}")
        except Exception as e:
            print(f"[失败] {ticker}: {e}")
            failed.append(ticker)
        time.sleep(0.1)

    print("\n全部完成。" if not failed else f"\n完成，但以下标的失败: {failed}")


if __name__ == "__main__":
    sys.exit(main())
