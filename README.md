# 成分股估值 · 选股工具

一个纯前端（单文件 HTML）的美股估值/技术面选股面板，按**最近一个交易日收盘**数据实时更新，只跟踪自选标的。仿富途「成分股估值」表，并加入 **RSI、行业均值PE**。

## 首次使用（配置 API key）
1. 复制 `config.example.js` 为 **`config.js`**
2. 编辑 `config.js`，把 `window.MASSIVE_API_KEY` 填成你的 [Massive](https://massive.com)/Polygon key
3. 双击 `index.html` 用浏览器打开（推荐 Chrome），无需服务器

> `config.js` 已被 `.gitignore` 忽略，**永不进 git**——所以仓库里不含任何密钥，推到公开/私有仓库都安全。

## 云端访问（其他设备 / 手机）
已部署 GitHub Pages：**https://crazyforsashimi.github.io/claude/**

- 页面**不含 key**（`config.js` 不部署）。任意设备首次打开会提示**输入一次 API key**，仅存该设备浏览器 `localStorage`，不上传、不进仓库。
- 之后随时可点工具栏 **🔑 API key** 更换。
- 陌生人打开网址没有你的 key → 只是空壳、拉不到数据，**“需要 key”即天然门槛**。
- key 解析优先级：本地 `config.js` > 该设备 `localStorage`。

---

## 关注标的（31 支）

| 分组 | 标的 |
|---|---|
| M7 | AAPL 苹果 · MSFT 微软 · GOOGL 谷歌-A · AMZN 亚马逊 · NVDA 英伟达 · META · TSLA 特斯拉 |
| 半导体 | TSM 台积电 · AVGO 博通 · AMD 超微 · MU 美光 · QCOM 高通 |
| 软件/互联网 | NET Cloudflare · SNOW Snowflake · BABA 阿里巴巴 |
| 电力/能源 | CEG 星座能源 · VST Vistra · NEE 新纪元 · GEV GE Vernova · LEU Centrus |
| 金融 | JPM 摩根大通 · GS 高盛 · MS 摩根士丹利 · BRK.B 伯克希尔-B · COIN Coinbase |
| 消费/工业/医药 | MCD 麦当劳 · CAT 卡特彼勒 · LLY 礼来 |
| ETF | QQQ 纳指100 · SPY 标普500 · SOXX 半导体 |

> GEV(GE Vernova) 2024-03 拆分上市，仅约 2 年历史(576 行)，回溯样本有限，主要用于实时告警。

在 `index.html` 顶部的 `UNIVERSE` 数组里增删标的即可。

---

## 列说明与数据来源

| 列 | 取值方式 | 实时? |
|---|---|---|
| 市值 | Massive/Polygon `v3/reference/tickers` → `market_cap`（权威值） | ✅ 实时 |
| 市盈率TTM | 一级：`收盘价 ÷ 摊薄EPS(TTM)`；二级（无摊薄EPS时）：`市值 ÷ 归母净利润`。财报取自 `vX/reference/financials` | ✅ 实时 |
| 行业均值PE | 自选股中**同板块（≥2支）**的 PE TTM 均值，随行情自动变 | ✅ 实时 |
| 近5年历史分位 | **实时计算** = 复权5年日线 ÷ 拆股还原的滚动TTM摊薄EPS → 历史PE序列 → 当前PE百分位。算不出则显示「—」（不冒充） | ✅ 实时 |
| RSI(14) | Wilder 法自算；≥70 超买(红)、≤30 超卖(绿) | ✅ 实时 |
| KDJ(9,3,3) | 显示 J 值；K≥80/J≥100 超买(红)、K≤20/J≤0 超卖(绿)；标金叉/死叉。悬停看 K/D/J | ✅ 实时 |
| MACD(12,26,9) | 金叉/死叉高亮；否则显示柱值(正绿负红)+零轴上下(多/空头区)。悬停看 DIF/DEA/柱 | ✅ 实时 |
| BOLL(20,2) | 按 %B 分：破上轨/近上轨/中轨/近下轨/破下轨(上红下绿)。悬停看上中下轨 | ✅ 实时 |
| 均线 | MA20/50/200 判多头/空头排列；价距关键均线≤1.5% 标「测MAxx」(潜在支撑/压力，琥珀)。悬停看各均线 | ✅ 实时 |

技术面指标全部由复权日线按标准公式实时计算；**RSI/MACD 已与 Polygon 官方指标端点交叉核对，几乎完全一致**。高亮：<b>红=看空/超买 · 绿=看多/超卖·金叉(左侧交易关注) · 琥珀=关键位测试</b>。

> **动态市盈率（Forward PE）已移除**：Massive/Polygon 不提供分析师预期数据，也无更好的可靠免费源，与其种入静态值冒充，不如不收录。

**数据源**：[Massive](https://massive.com)（原 Polygon.io）REST API，**Starter 档**（无限速、5年历史、24季度财报）。所有价格类指标按**最近收盘（EOD）**计。

### PE 口径校验（对 2026-07-17 富途截图 + SEC EDGAR）
用 SEC 官方 GAAP 摊薄EPS 复算，与富途分毫不差（证明富途也用 GAAP as-reported）：
- AAPL 40.40 · NVDA 31.06 · AVGO 61.70 · GOOGL 26.45 · AMZN 29.57 · META 23.49 · **LLY 41.89** — 全部 = 富途 ✅

唯一真实差异：
- JPM：本工具 16.33（= SEC = Polygon = GAAP 权威值）vs 富途 14.61 —— **富途那侧的口径/滞后**，我的值正确，不修正。

> 本工具统一用 **GAAP 摊薄EPS**（Polygon；漏收时用 SEC 覆盖；无则市值/归母净利润）。「LLY 因 IPR&D 减记」是早期误判——实为 Polygon 漏收季报，用 SEC 数据后完全吻合。

---

## 限制与口径

Massive/Polygon **Starter 档**已解锁 5 年历史、24 季度财报、无限速，因此**近5年分位已转为实时计算**。剩余限制：

- **动态市盈率（Forward PE）已移除**：Massive/Polygon 不提供分析师预期数据，无可靠免费源，故不收录（不种入静态值冒充）。
- **Polygon `vX` 基本面不可靠（已发现多处）**：经 SEC EDGAR 交叉核实——
  - **漏收季报**：GOOGL/AMZN/META/LLY 的 2026 Q1（公司 2026-04-30 已申报）Polygon 迄今未收录 → 工具用 **SEC 官方 TTM 摊薄EPS 覆盖**（`UNIVERSE.secEps`），PE 与富途分毫不差；Polygon 补上后自动切回。带 <b>ˢ</b> 标记。
  - **历史截断/异常值**：META 季度序列只到 2022-06（真实5年不足）且含异常值 → 分位无法可靠计算，**直接显示「—」**。
  - **无摊薄EPS**：BRK.B → 分位显示「—」。
  - 原则：算不出的分位**一律显示缺失，绝不用静态值冒充**。
- **校验结论**：剔除上述数据源缺陷后，本工具分位与富途基本一致（重合标的多数差 ≤3）。唯一真实口径差是 JPM（我的 16.2 = SEC = GAAP 权威值，富途 14.6 偏低是其自身口径）。
- **ETF（QQQ/SPY）** 不申报财报，无 PE/分位，仅显示价格类指标。

> 若将来想加「动态市盈率」：需换有分析师预期的数据源（如 Twelve Data Grow / FMP Premium ~$29/月）实时拉取，而非种入静态值。

### 维护 / 增删标的
`index.html` 的 `UNIVERSE` 数组：
- `fwd` = 动态PE 种入值（Massive 无预期数据；需更新时把最新富途快照发我，或自行编辑；`null`=显示「—」）
- `secEps` + `secEpsThru` = 某巨头被 Polygon 漏收季报时的 SEC 官方 TTM 摊薄EPS 覆盖（出新季报且 Polygon 仍滞后时更新一次；Polygon 追上后此值自动失效）
- 增删标的直接改数组

## Massive MCP（对话内查数据）
已在 `~/.claude.json`（user 作用域）添加远程 MCP：`massive → https://mcp.massive.com/`。**首次需 OAuth 认证**：在 Claude Code 里运行 `/mcp` → 选 massive → 浏览器登录。认证后，新会话里 Claude 可直接查 Massive 实时数据（权限随 Starter 套餐）。此 MCP 用于对话维护，**与本 HTML 工具的运行无关**（工具走 REST + apiKey）。

---

## API Key
key 存在 **`config.js`** 里（被 `.gitignore` 忽略，不入仓库），由 `index.html` 运行时读取。如需轮换，去 [massive.com](https://massive.com) 重新生成后改 `config.js` 即可。

---

## 文件结构
```
stock-screener/
├── index.html          # 工具本体（HTML/CSS/JS 全部逻辑）
├── config.example.js   # key 模板（复制为 config.js 填入你的 key）
├── config.js           # 你的真实 key（.gitignore 忽略，不入仓库）
├── download_history.py    # 轻量版：仅下载17支标的5年复权OHLCV
├── build_dataset.py       # 完整版：OHLCV + 技术指标 + 估值基本面 + 前瞻收益标签，供算法建模
├── build_labels.py        # 建模就绪层：三重障碍标签(3/2/20) + 派生特征 + 特征白/黑名单 → model_dataset.csv
├── train_model.py         # 买入检测器：HGB + Purged Walk-Forward（结论：综合特征预测20日方向样本外无 alpha）
├── edge_scanner.py        # 大机会条件扫描：超卖/回撤/支撑规则 + Wilson 置信下界排序 → edge_rules.csv
├── check_data_quality.py  # 数据质量体检：结构/OHLC一致性/极端跳变/指标越界/估值合理性/前视偏差/交易日历对齐
├── historical_data/       # build_dataset.py 的输出 CSV（.gitignore 忽略，不入仓库）
├── model_dataset.csv      # build_labels.py 的输出：pooled 建模数据集（.gitignore 忽略，不入仓库）
├── .gitignore
└── README.md
```

---

## 算法建模数据集（`build_dataset.py`）

`python3 build_dataset.py` 为17支自选标的各生成一份 `historical_data/{TICKER}.csv`，每行一个交易日，55列，分四类：

| 类别 | 列 | 说明 |
|---|---|---|
| 原始行情 | open/high/low/close/volume/vwap/transactions | 复权日线 |
| 技术面 | ret_1/5/20/60/252d、vol_20/60d_ann、MA5-200、EMA12/26、MACD(dif/dea/hist)、RSI14、KDJ(9,3,3)、BOLL(20,2)、ATR14、CCI20、威廉%R14、OBV、MFI14、vol_ma20/vol_ratio | RSI/MACD/KDJ/BOLL 公式与 `index.html` 完全一致(已交叉验证) |
| 估值/基本面 | pe_ttm、eps_ttm、pe_percentile_causal、pe_percentile_full_sample、pb、ps_ttm、roe_ttm、gross/operating_margin_ttm、leverage_ratio、market_cap_approx | 按财报 **filing_date**(而非 period_end) 前推到每个交易日，避免财报未公开前的未来数据泄露；EPS/股数已做拆股比例还原 |
| 标签(y) | fwd_ret_1/5/20d | 前瞻收益率，故意用未来数据，只能当监督学习目标，不能当特征 |

**PE分位两个口径，别混用**：
- `pe_percentile_causal`：只用截至当日为止的历史算分位（扩张窗口），可放心当特征。
- `pe_percentile_full_sample`：用全部5年样本算分位，和 `index.html` 实时工具口径一致，但对样本早期的行用到了"未来"数据，**只能核对展示，不能当训练特征**（否则前视偏差）。

---

## 建模就绪数据集（`build_labels.py`）

`python3 build_labels.py` 在 `historical_data/` 的干净日线上，产出 **`model_dataset.csv`**（31 支标的 pooled 堆叠，37808 行 × 81 列，含 `ticker` 列），供 LightGBM/XGBoost 训练**买入/卖出高精度信号**。定位：`build_dataset.py` 提供原始特征与前瞻收益，本脚本在其上加**可交易的标签**和**建模就绪的相对特征**。

### 标签：三重障碍法（Triple Barrier，绝对收益，参数 3/2/20）

对每个交易日（entry = 当日收盘价，ATR 在 entry 时刻固定），向未来看最多 20 个交易日，谁先触及谁结算：

| 视角 | 止盈障碍(成功) | 止损障碍(失败) | 时间障碍 | 标签列 |
|---|---|---|---|---|
| 买入 `tb_long` | entry **+3×ATR14** | entry −2×ATR14 | 20 交易日=中性 | 1=止盈先到 / 0=止损先到或到期 |
| 卖出 `tb_short` | entry **−3×ATR14** | entry +2×ATR14 | 20 交易日=中性 | 1=止盈先到 / 0=止损先到或到期 |

- **盈亏比 1.5:1**（3ATR : 2ATR）内生于障碍设置。持有期**内生浮动**（谁先碰谁结算），不依赖固定日期——这正是三重障碍相对「死盯第 N 日收盘」的优势。
- 二分类 `{0,1}`，**精度(precision) = 打了买入/卖出标签里实际止盈成功的比例**，正对「宁缺毋滥、要准」的诉求。
- 辅助列：`tb_*_touch`（up/down/time 实际触及哪条）、`tb_*_ret`（策略视角对数收益，成功为正）、`tb_*_days`（持有天数），供回测算真实期望值。
- **保守假设**（日线无盘中路径）：同日 high、low 同时越过上下障碍 → 一律判「止损方向先到」（失败），不夸大胜率；成交价按障碍价计，未建模跳空滑点（偏保守）。

### 目标与基准（重要）

- **目标：样本外(out-of-sample) 精度 70%+ / 盈亏比 1.5**，用阈值门控卡到每标的每年约 5–10 次信号。
- **基准正样本率：买入 38.5%、卖出 24.9%**（这几年科技股牛市，上涨机会多于下跌）。即随机打标签的精度就等于此值，**模型要把精度顶到 70%（≈翻倍）才算真有 alpha**。
- ⚠️ 「95% 回溯成功率」是 in-sample 过拟合幻觉，不可交易；一切以 **Purged Walk-Forward 的样本外精度**为准，决策看**期望值 = 胜率 × 盈亏比**而非单一胜率。

### 派生特征（现有列没有、对「大机会」判别有用，全部 causal 无前视偏差）

`dist_52w_high` 距52周高点距离 · `px_ma20/50/200` 价相对均线 · `ma20_ma50`/`ma50_ma200` 均线排列 · `above_ma200` 趋势过滤 · `macd_hist_norm` 归一化MACD柱 · `atr_pct` 波动率占价比 · `boll_bw` 布林带宽 · `obv_z` OBV标准分 · `excess_ret20_spy`/`excess_ret20_qqq` 相对大盘超额动量 · `vol20_pctile` 波动率历史分位(扩张窗口) · `log_mktcap` 规模。

### 前视偏差控制清单（特征白/黑名单，防误用）

- ✅ **白名单 `FEATURE_COLS`（38 列）**：只含无量纲/相对/有界特征，跨标的可比。分**核心技术面 30 列**（要求非空才算 trainable）+ **基本面 8 列**（允许 NaN，树模型原生处理，故 ETF/BRK-B 也能进）。
- 🚫 **黑名单 `BLACKLIST`**：
  - `fwd_ret_1/5/20d`、`tb_*` 全部标签列 → 是 y，不能当特征；
  - `pe_percentile_full_sample` → **全样本分位=前视偏差**（已在 `build_dataset.py` 隔离）；
  - 所有**价格绝对水平列**（open/high/low/close/vwap、ma*、ema*、macd_dif/dea/hist、boll_mid/up/low、atr14、obv、vol_ma20、market_cap_approx、eps_ttm、pe_ttm）→ 跨标的量纲不可比、会让模型「背」价格水平，已用相对/归一化版本替代。
- `trainable_long` / `trainable_short` 标志列：核心技术面特征齐全 **且** 对应标签非空为 `True`（每标的前约 250 行暖机期、末 20 行窗口不满自动为 `False`）。合计可训练**买入 29610 行、卖出 29595 行**。

---

## 大机会告警（`edge_scanner.py` + `index.html` 集成）

**方法论转折**:`train_model.py`(HistGradientBoosting + Purged Walk-Forward)验证"综合几十个特征预测未来20日方向"——样本外 **AUC≈0.49、精度天花板 36.7%,且阈值越高精度越低**,即模型学的是噪音,**没有择时 alpha**(符合弱式有效市场)。低阈值那点正收益纯是 2022–2026 牛市 beta,不是选股能力。

于是转向**条件边际扫描(conditional edge)**:不在模糊地带排序,只挖分布**尾部的极端条件**。`edge_scanner.py` 扫一批超卖/回撤/支撑规则及组合,每条报告触发次数、上涨概率、**Wilson 95% 置信下界**(小样本自动降权,杜绝"N=3 的假 95%")、edge(超额于无条件基准 56.5%)、平均收益、三重障碍盈亏比,按 Wilson 下界排序 → `edge_rules.csv`。

**近5年回溯验证的核心规则(已集成进 `index.html` 顶部"⚡当前大机会"告警横幅 + "机会"列)**:

| 告警 | 触发条件 | 回溯统计 |
|---|---|---|
| 🟢 **强买入(抄底★)** | `RSI<20` 极端超卖 | 触发37次、20日**上涨 87%、Wilson 下界 72%、平均 +10.7%、盈亏比 9.8** |
| 🟢 **买入** | `RSI<25` 深度超卖 | 触发208次、20日上涨 79%、Wilson 下界 73%、平均 +8.9%、盈亏比 3.4 |
| 🟠 **减仓(风险提示)** | `PE五年分位>95 且 RSI>70`(高估值+超买) | 31标的回溯：下跌概率51%、edge+7.5%、预期收益压到~0（非做空） |

**数据两次证伪的教训**:
- 单纯"碰均线(50周线/ma200)、深度回撤、连跌"**无 edge**(edge≈0 甚至为负);有效的永远是**深度超卖**(RSI 主导,其次 CCI、破布林下轨)。
- **做空"超买/高估值"是负期望**——强势股超买后 20 日平均还涨 3%,做空障碍胜率仅 21–29%。故减仓信号**仅作规避止盈,绝不代表做空**。
- 判断规则一律看 **edge(超额于基准)**,不看绝对胜率——牛市里无条件基准就有 56.5% 上涨。95% 只在极小样本上偶现,不可交易;`RSI<20` 的"72% 保守胜率 × 9.8 盈亏比"才是真正的大机会。扩池到 31 标的后,高波动新标的(NET/SNOW/COIN/MU 等)把 `RSI<20` 从"样本不足(15次)"补到 37 次、稳上★榜——这正是扩池的核心收获。

---

## 数据质量体检（`check_data_quality.py`）

`python3 check_data_quality.py` 对全部17个CSV跑7类自动检查：结构完整性、OHLC内部一致性、极端单日跳变(区分"多标的同日大动=真实市场事件"/"次日大幅反向抵消=疑似坏tick"/"孤立跳变=需人工复核")、技术指标越界、估值字段合理性、PE分位前视偏差自检(截断重算比对)、跨标的交易日历对齐。

**已发现并修复**：META 在 2021-07-22~2022-01-28 期间，Polygon/Massive 返回的收盘价系统性错误（约$12-15，真实值应为$300+），随后 2022-01-29~2022-06-08 又整体缺失约90个交易日，2022-06-09起才恢复正常且与真实股价吻合。`build_dataset.py` 现在会自动探测"交易日历大缺口(>10天) + 缺口前后价格跳变(>3倍)且无拆股记录能解释"，命中即丢弃缺口之前的不可靠数据 —— META.csv 因此从 2022-06-09 开始（1030行），而非17支标的默认的1253行。此逻辑是通用检测，不是针对META硬编码，未来若其他标的出现同类供应商数据错误也会自动处理。

**复核后确认为真实事件、未做改动**的孤立单日大波动（均有对应大幅放量佐证，非稀薄成交造成的异常）：NVDA 2023-05-25(+24%,AI业绩指引)、AVGO 2024-12-13(+24%,AI芯片业绩指引)、CEG 2024-09-20/2025-01-10/2025-01-27(核电重启/AI供电协议+DeepSeek冲击)、META 2022-10-27/2023-02-02/2024-02-02(财报暴跌/暴涨)、TSLA 2024-10-24(财报)、LEU多次±20-33%(铀燃料小盘股，真实高波动性)。

**已知限制**（与 `index.html` 的口径限制一致）：
- ETF(QQQ/SPY) 不申报财报 → 估值列全部留空，不冒充。
- BRK.B 无摊薄EPS → 估值列留空。
- 部分标的(如GOOGL/AMZN/META/LLY)近几季 Polygon 财报漏收时，`index.html` 用 SEC 官方EPS覆盖，但本批量脚本未接入该覆盖（会随 Polygon 补数据自动修正），近期几行 PE 可能偏高/偏旧。
- 已做「TTM完整性校验」：若某季度财报缺失(如 META 曾缺 2022Q4)导致 trailing-4 拼出的TTM跨度不是完整年度，直接判该行估值缺失，不用错位数据冒充。
- 无 forward PE / 分析师预期、无逐笔/盘口数据、无 Fama-French 式全市场横截面因子 — Massive Starter 档不提供，未来若升级套餐或换数据源可再补充。

## 变更记录
- **v12（2026-07-21）**：标的池 17→31（+14）。新增半导体(AMD/MU/QCOM)、软件云(NET/SNOW)、电力(VST/NEE/GEV)、工业(CAT)、加密(COIN)、中概(BABA)、金融(GS/MS)、半导体ETF(SOXX)——高波动标的扩充极端超卖样本。**直接收获：`RSI<20` 从"样本不足(15次)"升级为★强规则(37次/20日涨87%/Wilson下界72%/盈亏比9.8)**；`index.html` 告警门槛改为分层 `RSI<20`强买入★ / `RSI<25`买入。(DRAM 查出是 2026-04 新上市 ETF→剔除；GEV 仅 2 年历史→保留但回溯样本有限。)扩池后重验减仓规则：纯"PE分位>95且贴顶"edge 从 +9.5% 缩到 +1.8% 失效，改用"PE分位>95且RSI>70"(edge +7.5%、下跌51%)。
- **v11（2026-07-21）**：大机会信号系统落地。`train_model.py`(HGB + Purged Walk-Forward)证明综合特征预测20日方向样本外 AUC≈0.49、无 alpha;转而用 `edge_scanner.py` 条件边际扫描(Wilson 下界排序)挖出 `RSI<22`(20日涨94%/下界81%/盈亏比5.4)等高胜率抄底规则。已集成进 `index.html`:顶部"⚡当前大机会"告警横幅 + "机会"列(🟢买入 RSI<22 / 🟠减仓 PE分位>95且贴52周高)。数据证伪:碰均线/深回撤无 edge、做空超买/高估值为负期望(仅作规避止盈,不代表做空)。
- **v10（2026-07-21）**：新增建模就绪层 `build_labels.py` → `model_dataset.csv`。三重障碍标签（绝对收益，止盈+3ATR/止损−2ATR/时间20日，盈亏比1.5）产出二分类 `tb_long`/`tb_short`；新增 12 个 causal 派生特征（距52周高、价相对均线、相对大盘超额动量、波动率分位等）；固化 38 列特征白名单 + 黑名单（隔离 `pe_percentile_full_sample` 前视偏差列和所有价格绝对水平列）。目标：样本外精度 70%+ / 盈亏比 1.5；基准正样本率买入 38%、卖出 24.8%。
- **v9（2026-07-21）**：技术面扩充。新增 **KDJ(9,3,3) / MACD(12,26,9) / BOLL(20,2) / 关键均线(MA20/50/200)**，各设分类+高亮（超买红/超卖·金叉绿/关键位琥珀），悬停看完整数值。RSI/MACD 已与 Polygon 官方指标端点交叉核对一致。
- **v8（2026-07-21）**：移除「动态市盈率」列（无可靠数据源，不种入冒充）和「情绪评分」列。
- **v7（2026-07-21）**：SEC 交叉核验修正数据源缺陷。发现 Polygon `vX` 漏收 GOOGL/AMZN/META/LLY 的 2026 Q1（SEC 证实已申报）→ 用 SEC 官方 EPS 覆盖（`secEps`），带 ˢ 标记、Polygon 补上自动切回；META 历史截断、BRK.B 无摊薄EPS → 分位显示「—」缺失（**不再用静态种入值冒充**）。重合标的分位与富途基本一致（多数差≤3）。
- **v6（2026-07-20）**：支持云端访问。部署 GitHub Pages；无 config.js 时（如云端）弹出 key 输入框，key 存该设备 localStorage；工具栏加 🔑 换 key 按钮。
- **v5（2026-07-20）**：API key 从 `index.html` 剥离到 `config.js`（`.gitignore` 忽略）；重置 git 历史，确保仓库任何提交都不含密钥，可安全推送。
- **v4（2026-07-20）**：加「财报滞后」检测。数据源某股最新季度 >140 天时（如 GOOGL Polygon 迄今最新仅到 2025-12-31、缺 2026 季报），TTM 偏旧会使 PE/分位偏高——在 PE/分位加 `*` 警告星号 + 悬停说明，数据源补上后自动修正。
- **v3（2026-07-20）**：修复拆股导致的 5年分位偏差。历史 EPS 按拆股因子还原到当前股本口径 + 改用复权价，避免拆股过渡窗口的垃圾PE。校验：**NVDA 35%→2%（图1%）、AVGO 77%→61%（图60%）**，AAPL/MSFT/TSLA 不变。
- **v2（2026-07-20）**：升级 Massive Starter。**近5年分位转为实时计算**（5年日线+24季度EPS重构历史PE）；移除 5次/分钟限速，改并发抓取（刷新 10 分钟 → ~30 秒）；仅剩「动态市盈率」种入。加 Massive 远程 MCP（user 作用域）。
- v1（2026-07-20）：首版。7 列实时/计算 + 2 列快照种入；板块筛选、列排序、本地缓存、限速队列。
