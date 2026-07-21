#!/usr/bin/env python3
"""买入检测器（tb_long）——Purged Walk-Forward 验证 + 精度阈值门控 + 回测。

目标：样本外(out-of-sample) 精度 70%+ / 盈亏比 1.5，靠高阈值只在最有把握的少数时点打标签。

流程：
  1) 读 model_dataset.csv 的 trainable_long 行，X=38 列特征白名单，y=tb_long{0,1}。
  2) Purged Walk-Forward：anchored expanding 训练，逐段向未来验证；训练集与验证集之间
     purge 掉 HORIZON(20) 个交易日，斩断三重障碍标签的前瞻重叠泄漏。
  3) 汇总各折**样本外**预测概率(OOF)，扫描阈值 → 精度 vs 信号频率曲线，定位 70% 精度点。
  4) 在该阈值下用 tb_long_ret 回测：胜率、盈亏比、每笔期望、年化信号频率。
  5) permutation importance 看哪些特征在驱动信号。

模型：sklearn HistGradientBoostingClassifier（直方图梯度提升，原生吃 NaN，强正则防过拟合）。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).parent
DATA = ROOT / "model_dataset.csv"
HORIZON = 20   # 与 build_labels.py 一致：purge 掉训练尾部 20 交易日，防标签重叠泄漏

CORE_FEATURES = [
    "ret_1d", "ret_5d", "ret_20d", "ret_60d", "ret_252d",
    "vol_20d_ann", "vol_60d_ann", "vol20_pctile", "atr_pct", "boll_bw",
    "rsi14", "kdj_k", "kdj_d", "kdj_j", "cci20", "willr14", "mfi14", "boll_pctb",
    "vol_ratio", "obv_z",
    "px_ma20", "px_ma50", "px_ma200", "ma20_ma50", "ma50_ma200", "above_ma200",
    "dist_52w_high", "macd_hist_norm",
    "excess_ret20_spy", "excess_ret20_qqq",
]
FUND_FEATURES = [
    "pe_percentile_causal", "pb", "ps_ttm", "roe_ttm",
    "gross_margin_ttm", "operating_margin_ttm", "leverage_ratio", "log_mktcap",
]
FEATURES = CORE_FEATURES + FUND_FEATURES

# 每段验证窗的左边界（半年一段），anchored expanding：train=该边界之前(减purge)，test=[边界,下一边界)
SEG_BOUNDS = ["2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01",
              "2025-07-01", "2026-01-01", "2026-08-01"]

HGB_PARAMS = dict(
    max_iter=400, learning_rate=0.03, max_leaf_nodes=31,
    min_samples_leaf=100, l2_regularization=1.0,
    max_bins=255, early_stopping=False, random_state=42,
)


def load():
    df = pd.read_csv(DATA, parse_dates=["date"])
    df = df[df["trainable_long"]].reset_index(drop=True)
    return df.sort_values("date").reset_index(drop=True)


def purged_walk_forward(df: pd.DataFrame):
    """产出各段 (train_idx, test_idx)，训练集尾部 purge 掉 HORIZON 个交易日。"""
    calendar = np.array(sorted(df["date"].unique()))   # 全体交易日历
    pos = {d: i for i, d in enumerate(calendar)}
    folds = []
    for i in range(len(SEG_BOUNDS) - 1):
        seg_start = pd.Timestamp(SEG_BOUNDS[i])
        seg_end = pd.Timestamp(SEG_BOUNDS[i + 1])
        test_mask = (df["date"] >= seg_start) & (df["date"] < seg_end)
        if test_mask.sum() == 0:
            continue
        # purge：训练集只能到 seg_start 往前数 HORIZON 个交易日之前
        cut_pos = np.searchsorted(calendar, seg_start.to_datetime64()) - HORIZON
        if cut_pos <= 0:
            continue
        cut_date = calendar[cut_pos]
        train_mask = df["date"] < cut_date
        if train_mask.sum() < 2000:      # 训练样本太少的早期段跳过
            continue
        folds.append((seg_start, seg_end, np.where(train_mask)[0], np.where(test_mask)[0]))
    return folds


def main():
    df = load()
    X = df[FEATURES].to_numpy(dtype=float)
    y = df["tb_long"].to_numpy(dtype=int)
    ret = df["tb_long_ret"].to_numpy(dtype=float)

    folds = purged_walk_forward(df)
    oof_proba = np.full(len(df), np.nan)
    print(f"样本 {len(df)} 行 · 特征 {len(FEATURES)} 列 · 折数 {len(folds)}\n")
    print(f"{'验证段':<22}{'训练n':>8}{'验证n':>8}{'正样本率':>9}{'AUC':>7}{'AP':>7}")
    for seg_start, seg_end, tr, te in folds:
        model = HistGradientBoostingClassifier(**HGB_PARAMS)
        model.fit(X[tr], y[tr])
        p = model.predict_proba(X[te])[:, 1]
        oof_proba[te] = p
        auc = roc_auc_score(y[te], p) if len(np.unique(y[te])) > 1 else float("nan")
        ap = average_precision_score(y[te], p)
        seg = f"{seg_start.date()}~{seg_end.date()}"
        print(f"{seg:<22}{len(tr):>8}{len(te):>8}{y[te].mean():>8.1%}{auc:>7.3f}{ap:>7.3f}")

    m = ~np.isnan(oof_proba)
    yv, pv, rv = y[m], oof_proba[m], ret[m]
    base_rate = yv.mean()
    years = (df["date"].max() - pd.Timestamp(SEG_BOUNDS[0])).days / 365.25
    n_tickers = df["ticker"].nunique()

    print(f"\n合并样本外(OOF): {m.sum()} 行 · 基准正样本率 {base_rate:.1%} "
          f"· 覆盖 {years:.1f} 年 × {n_tickers} 标的 · 整体 AUC {roc_auc_score(yv, pv):.3f}")

    # ---- 阈值扫描：精度 vs 信号频率 ----
    print(f"\n{'阈值':>6}{'信号数':>8}{'占比':>7}{'精度':>8}{'每标的/年':>10}"
          f"{'胜率':>7}{'盈亏比':>7}{'每笔期望':>9}")
    grid = np.round(np.arange(0.50, 0.951, 0.05), 2)
    curve = []
    for thr in grid:
        sig = pv >= thr
        n = int(sig.sum())
        if n < 20:
            continue
        prec = yv[sig].mean()
        wins, losses = rv[sig & (yv == 1)], rv[sig & (yv == 0)]
        payoff = wins.mean() / abs(losses.mean()) if len(losses) and losses.mean() != 0 else float("nan")
        exp = rv[sig].mean()
        freq = n / (n_tickers * years)
        curve.append((thr, n, n / m.sum(), prec, freq, payoff, exp))
        print(f"{thr:>6.2f}{n:>8}{n/m.sum():>7.1%}{prec:>8.1%}{freq:>9.1f}"
              f"{prec:>7.1%}{payoff:>7.2f}{exp:>+9.2%}")

    # ---- 定位 70% 精度阈值 ----
    hit = [c for c in curve if c[3] >= 0.70]
    print("\n" + "=" * 64)
    if hit:
        thr, n, frac, prec, freq, payoff, exp = hit[0]
        print(f"✅ 样本外精度达 70% 的最低阈值 = {thr:.2f}")
        print(f"   精度 {prec:.1%} · 盈亏比 {payoff:.2f} · 每笔期望 {exp:+.2%} · "
              f"信号 {n} 次 = 每标的每年 {freq:.1f} 次")
        verdict = "够得着" if (prec >= 0.70 and payoff >= 1.5) else \
                  "精度达标但盈亏比欠火候" if prec >= 0.70 else "—"
        print(f"   判定：70% 精度 + 1.5 盈亏比 → {verdict}")
    else:
        best = max(curve, key=lambda c: c[3])
        print(f"❌ 样本外精度未触及 70%。最高精度 = {best[3]:.1%} @ 阈值 {best[0]:.2f}"
              f"（信号 {best[1]} 次，盈亏比 {best[5]:.2f}）")
        print("   含义：当前特征+标签下 70% 够不着，需迭代（见下方特征重要性找方向）。")

    # ---- permutation importance（最后一折模型，样本外算，稳健）----
    seg_start, seg_end, tr, te = folds[-1]
    model = HistGradientBoostingClassifier(**HGB_PARAMS).fit(X[tr], y[tr])
    imp = permutation_importance(model, X[te], y[te], scoring="average_precision",
                                 n_repeats=5, random_state=42, n_jobs=-1)
    order = np.argsort(imp.importances_mean)[::-1][:12]
    print(f"\nTop 12 驱动特征（permutation importance, 末折样本外 AP 下降）：")
    for i in order:
        print(f"   {FEATURES[i]:<20}{imp.importances_mean[i]:+.4f}")

    # ---- 输出图 + OOF ----
    prm = np.array([(c[4], c[3]) for c in curve])   # (每标的年频, 精度)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(prm[:, 0], prm[:, 1] * 100, "o-", color="#2563eb")
    ax.axhline(70, ls="--", color="#dc2626", lw=1, label="70% target")
    ax.axhline(base_rate * 100, ls=":", color="#6b7280", lw=1, label=f"base rate {base_rate:.0%}")
    ax.set_xlabel("signals per ticker per year")
    ax.set_ylabel("out-of-sample precision %")
    ax.set_title("Buy detector: precision vs signal frequency (threshold gating)")
    ax.legend(); ax.grid(alpha=.3); fig.tight_layout()
    fig.savefig(ROOT / "precision_curve.png", dpi=130)
    df.loc[m, ["ticker", "date", "tb_long", "tb_long_ret"]].assign(proba=pv) \
        .to_csv(ROOT / "oof_predictions.csv", index=False)
    print(f"\n已存 precision_curve.png（精度-频率曲线）、oof_predictions.csv（样本外预测）")


if __name__ == "__main__":
    sys.exit(main())
