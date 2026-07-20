# 成分股估值 · 选股工具

一个纯前端（单文件 HTML）的美股估值/技术面选股面板，按**最近一个交易日收盘**数据实时更新，只跟踪自选标的。仿富途「成分股估值」表，并加入 **RSI、情绪评分、行业均值PE**。

## 首次使用（配置 API key）
1. 复制 `config.example.js` 为 **`config.js`**
2. 编辑 `config.js`，把 `window.MASSIVE_API_KEY` 填成你的 [Massive](https://massive.com)/Polygon key
3. 双击 `index.html` 用浏览器打开（推荐 Chrome），无需服务器

> `config.js` 已被 `.gitignore` 忽略，**永不进 git**——所以仓库里不含任何密钥，推到公开/私有仓库都安全。

---

## 关注标的（17 支）

| 分组 | 标的 |
|---|---|
| M7 | AAPL 苹果 · MSFT 微软 · GOOGL 谷歌-A · AMZN 亚马逊 · NVDA 英伟达 · META · TSLA 特斯拉 |
| 个股 | MCD 麦当劳 · TSM 台积电 · JPM 摩根大通 · CEG 星座能源 · AVGO 博通 · BRK.B 伯克希尔-B · LEU Centrus能源 · LLY 礼来 |
| ETF | QQQ 纳指100 · SPY 标普500 |

在 `index.html` 顶部的 `UNIVERSE` 数组里增删标的即可。

---

## 列说明与数据来源

| 列 | 取值方式 | 实时? |
|---|---|---|
| 市值 | Massive/Polygon `v3/reference/tickers` → `market_cap`（权威值） | ✅ 实时 |
| 市盈率TTM | 一级：`收盘价 ÷ 摊薄EPS(TTM)`；二级（无摊薄EPS时）：`市值 ÷ 归母净利润`。财报取自 `vX/reference/financials` | ✅ 实时 |
| 动态市盈率 | **快照种入**（Massive 无分析师预期数据；见下方「限制」） | ⚠️ 手动 |
| 行业均值PE | 自选股中**同板块（≥2支）**的 PE TTM 均值，随行情自动变 | ✅ 实时 |
| 近5年历史分位 | **实时计算** = 未复权5年日线 ÷ 当期滚动TTM摊薄EPS → 历史PE序列 → 当前PE百分位 | ✅ 实时 |
| RSI(14) | 由日线收盘价按 Wilder 方法自算；≥70 超买、≤30 超卖 | ✅ 实时 |
| 情绪评分 | `0.4×RSI + 0.3×52周位置 + 0.3×趋势`；趋势 = 价格是否站上 MA50/MA200，0–100 分 | ✅ 实时 |

**数据源**：[Massive](https://massive.com)（原 Polygon.io）REST API，**Starter 档**（无限速、5年历史、24季度财报）。所有价格类指标按**最近收盘（EOD）**计。

### PE 口径校验（对 2026-07-17 富途截图）
精确命中（干净盈利，GAAP≈非GAAP）：
- AAPL 40.40 = 富途 40.40 ✅ · NVDA 31.06 = 31.06 ✅ · AVGO 61.70 = 61.70 ✅ · BRK.B 14.61 = 14.61 ✅（市值/净利润兜底）

口径差异（有一次性项目，富途用调整后/非GAAP）：
- LLY 51.38 vs 富途 41.89（药企 IPR&D 减记压低 GAAP EPS）
- JPM 16.33 vs 富途 14.61（银行口径 + 摊薄EPS 20.89，对应 $341 其实 PE≈16）

> 本工具统一用 **GAAP 摊薄EPS**（无则市值/归母净利润），口径透明、自身一致；与用非GAAP的平台在个别名字上会有差异，属正常。

---

## 限制与口径

Massive/Polygon **Starter 档**已解锁 5 年历史、24 季度财报、无限速，因此**近5年分位已转为实时计算**。剩余限制：

- **动态市盈率（Forward PE）**：Massive/Polygon **不提供分析师预期数据**（`ratios` 端点也无 forward PE，且更高档才开放）。这列仍用 **2026-07-17 富途成分股估值截图**种入（变化慢）。
- **近5年分位口径**：本工具用 **GAAP 摊薄EPS** 重构历史 PE。校验：AAPL/MSFT/TSLA 与富途吻合；**盈利波动大或含一次性项目的（NVDA/JPM/LLY）**因 GAAP vs 富途(非GAAP) 口径不同会有差异，属正常。`UNIVERSE` 里的 `pct` 仅作实时算不出时（如 ETF）的兜底显示（虚线标注）。
- **ETF（QQQ/SPY）** 不申报财报，无 PE/分位，仅显示价格类指标。

> 想让「动态市盈率」也实时：需换有分析师预期的数据源（如 Twelve Data Grow / FMP Premium ~$29/月），在代码里把 `fwd` 种入逻辑换成 API 拉取。

### 更新种入值 / 增删标的
`index.html` 的 `UNIVERSE` 数组：`fwd` = 动态PE 种入值（需更新时把最新富途快照发我，或自行编辑）；增删标的直接改数组。`null` = 待补（显示「—」）。

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
├── .gitignore
└── README.md
```

## 变更记录
- **v5（2026-07-20）**：API key 从 `index.html` 剥离到 `config.js`（`.gitignore` 忽略）；重置 git 历史，确保仓库任何提交都不含密钥，可安全推送。
- **v4（2026-07-20）**：加「财报滞后」检测。数据源某股最新季度 >140 天时（如 GOOGL Polygon 迄今最新仅到 2025-12-31、缺 2026 季报），TTM 偏旧会使 PE/分位偏高——在 PE/分位加 `*` 警告星号 + 悬停说明，数据源补上后自动修正。
- **v3（2026-07-20）**：修复拆股导致的 5年分位偏差。历史 EPS 按拆股因子还原到当前股本口径 + 改用复权价，避免拆股过渡窗口的垃圾PE。校验：**NVDA 35%→2%（图1%）、AVGO 77%→61%（图60%）**，AAPL/MSFT/TSLA 不变。
- **v2（2026-07-20）**：升级 Massive Starter。**近5年分位转为实时计算**（5年日线+24季度EPS重构历史PE）；移除 5次/分钟限速，改并发抓取（刷新 10 分钟 → ~30 秒）；仅剩「动态市盈率」种入。加 Massive 远程 MCP（user 作用域）。
- v1（2026-07-20）：首版。7 列实时/计算 + 2 列快照种入；板块筛选、列排序、本地缓存、限速队列。
