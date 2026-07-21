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
| 行业均值PE | 自选股中**同板块（≥2支）**的 PE TTM 均值，随行情自动变 | ✅ 实时 |
| 近5年历史分位 | **实时计算** = 复权5年日线 ÷ 拆股还原的滚动TTM摊薄EPS → 历史PE序列 → 当前PE百分位。算不出则显示「—」（不冒充） | ✅ 实时 |
| RSI(14) | 由日线收盘价按 Wilder 方法自算；≥70 超买、≤30 超卖 | ✅ 实时 |

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
├── .gitignore
└── README.md
```

## 变更记录
- **v8（2026-07-21）**：移除「动态市盈率」列（无可靠数据源，不种入冒充）和「情绪评分」列。当前列：市值 / 市盈率TTM / 行业均值PE / 近5年分位 / RSI(14)。
- **v7（2026-07-21）**：SEC 交叉核验修正数据源缺陷。发现 Polygon `vX` 漏收 GOOGL/AMZN/META/LLY 的 2026 Q1（SEC 证实已申报）→ 用 SEC 官方 EPS 覆盖（`secEps`），带 ˢ 标记、Polygon 补上自动切回；META 历史截断、BRK.B 无摊薄EPS → 分位显示「—」缺失（**不再用静态种入值冒充**）。重合标的分位与富途基本一致（多数差≤3）。
- **v6（2026-07-20）**：支持云端访问。部署 GitHub Pages；无 config.js 时（如云端）弹出 key 输入框，key 存该设备 localStorage；工具栏加 🔑 换 key 按钮。
- **v5（2026-07-20）**：API key 从 `index.html` 剥离到 `config.js`（`.gitignore` 忽略）；重置 git 历史，确保仓库任何提交都不含密钥，可安全推送。
- **v4（2026-07-20）**：加「财报滞后」检测。数据源某股最新季度 >140 天时（如 GOOGL Polygon 迄今最新仅到 2025-12-31、缺 2026 季报），TTM 偏旧会使 PE/分位偏高——在 PE/分位加 `*` 警告星号 + 悬停说明，数据源补上后自动修正。
- **v3（2026-07-20）**：修复拆股导致的 5年分位偏差。历史 EPS 按拆股因子还原到当前股本口径 + 改用复权价，避免拆股过渡窗口的垃圾PE。校验：**NVDA 35%→2%（图1%）、AVGO 77%→61%（图60%）**，AAPL/MSFT/TSLA 不变。
- **v2（2026-07-20）**：升级 Massive Starter。**近5年分位转为实时计算**（5年日线+24季度EPS重构历史PE）；移除 5次/分钟限速，改并发抓取（刷新 10 分钟 → ~30 秒）；仅剩「动态市盈率」种入。加 Massive 远程 MCP（user 作用域）。
- v1（2026-07-20）：首版。7 列实时/计算 + 2 列快照种入；板块筛选、列排序、本地缓存、限速队列。
