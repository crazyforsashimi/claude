# legacy/ · 归档脚本

这里放**已不在活跃管线里**的脚本:没有任何文件 `import` 它们,两个 GitHub Actions
workflow(`daily-alert` / `monthly-stats`)也都不调用它们。删掉它们对线上功能
(工具页面、每日邮件、月度数据重算)**零影响**——留在这里仅作历史与方法论参考。

| 脚本 | 是什么 | 为什么归档 |
|---|---|---|
| `train_model.py` | 买入检测器(HistGradientBoosting + Purged Walk-Forward) | **方法被证伪**:综合几十个特征预测未来20日方向,样本外 AUC≈0.49、无 alpha(符合弱式有效市场)。据此转向条件边际扫描。 |
| `edge_scanner.py` | 大机会条件扫描原型(分组回溯 + Wilson 下界 → `output/edge_rules.csv`) | 信号方法论的**原型**,现已被 per-ticker 双窗口校准 `gen_signal_config.py` 取代。 |
| `download_history.py` | 下载 5 年复权 OHLCV → `historical_data/` | 被功能更全的 `build_dataset.py`(含指标+估值+前瞻收益)取代。 |
| `check_data_quality.py` | 数据质量体检(7 类自动检查) | 手动质检工具,重建数据时偶尔复用,不属于自动管线。 |

## 运行方式

这些脚本的 `ROOT` 已调整为 `Path(__file__).parent.parent`(回指仓库根),所以数据
路径仍指向根目录的 `output/`、`historical_data/`、`config.js`。**从仓库根运行**:

```bash
python3 legacy/edge_scanner.py
python3 legacy/check_data_quality.py
```

> 归档时间:2026-07-24。方法论来龙去脉见主 `README.md` 的「大机会告警」「方法论转折」段。
