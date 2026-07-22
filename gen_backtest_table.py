#!/usr/bin/env python3
"""生成「31 标的 · 买入/强买入信号历史回溯」查阅表 → backtest_stats.html（GitHub Pages 可访问）。

口径与 build_ticker_stats / daily_alert 完全一致：近5年日线，同一批信号(以能算满20日为准)看
5日/10日/20日三个持有期的方向胜率(收盘价 vs 信号日收盘，涨为对)。按 Tier2 分组组织。
数据源：output/model_dataset.csv（build_dataset→build_labels 生成）。重跑：python gen_backtest_table.py
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "output" / "model_dataset.csv"

HI_VOL = {"LEU", "COIN", "NET", "SNOW", "TSLA", "AMD", "GEV", "MU", "NVDA", "BABA", "CEG", "VST", "AVGO"}
MOM_DIP = {"NVDA", "AVGO", "MU", "AMD", "GEV", "CEG", "LEU", "VST"}
MOM_BIG = {"SNOW", "TSLA", "BABA"}
NAMES = {
    "AAPL": "苹果", "MSFT": "微软", "GOOGL": "谷歌", "AMZN": "亚马逊", "NVDA": "英伟达",
    "META": "Meta", "TSLA": "特斯拉", "MCD": "麦当劳", "TSM": "台积电", "JPM": "摩根大通",
    "CEG": "星座能源", "AVGO": "博通", "BRK.B": "伯克希尔", "LEU": "Centrus", "LLY": "礼来",
    "AMD": "超微", "MU": "美光", "QCOM": "高通", "NET": "Cloudflare", "SNOW": "Snowflake",
    "VST": "Vistra", "NEE": "新纪元", "GEV": "GE Vernova", "CAT": "卡特彼勒", "COIN": "Coinbase",
    "BABA": "阿里", "GS": "高盛", "MS": "摩根士丹利", "QQQ": "纳指100", "SPY": "标普500", "SOXX": "半导体ETF",
}
# 信号定义：(标签, 触发档色 sig-strong/sig-buy)
SIG_LABEL = {
    "rsi20": ("强买入 · RSI(14)&lt;20", "strong"),
    "rsi25": ("买入 · RSI(14)&lt;25", "buy"),
    "b100":  ("买入 · 破100日布林下轨", "buy"),
    "dip":   ("买入 · 破下轨且价MA200上", "buy"),
}


def main():
    d = pd.read_csv(DATA).sort_values(["ticker", "date"]).reset_index(drop=True)
    for h in (5, 10, 20):
        d[f"fwd{h}"] = d.groupby("ticker")["close"].shift(-h) / d["close"] - 1
    d = d[d["fwd20"].notna()].copy()
    d["ma100"] = d.groupby("ticker")["close"].transform(lambda s: s.rolling(100).mean())
    d["std100"] = d.groupby("ticker")["close"].transform(lambda s: s.rolling(100).std())
    d["b100"] = d.close <= d.ma100 - 2 * d.std100
    masks = {
        "rsi20": d.rsi14 < 20,
        "rsi25": d.rsi14 < 25,
        "b100": d.b100,
        "dip": (d.boll_pctb < 0) & (d.px_ma200 > 0),
    }

    def stat(tk, key):
        s = d[(d.ticker == tk) & masks[key].fillna(False)]
        n = len(s)
        if not n:
            return None
        avg20 = (s["fwd20"].mean()) * 100
        return (n, *[round((s[f"fwd{h}"] > 0).mean() * 100) for h in (5, 10, 20)], avg20)

    # 每组：标的顺序 + 该组适用的信号
    GROUPS = [
        ("🛡️ 稳健组", "均值回归 · 非高波动 18 只", "#12924f",
         [t for t in NAMES if t not in HI_VOL], ["rsi20", "rsi25", "b100"]),
        ("🚀 趋势回调组", "半导体/AI硬件/电力 · 破日线下轨且价MA200上", "#4f46e5",
         [t for t in NAMES if t in MOM_DIP], ["dip"]),
        ("🏛️ 大级别支撑组", "SNOW/TSLA/BABA · 破100日布林(≈20周级)", "#b45309",
         [t for t in NAMES if t in MOM_BIG], ["b100"]),
    ]

    def pct_td(v, n):
        cls = "hi" if v >= 70 else "mid" if v >= 50 else "lo"
        faint = " faint" if n < 5 else ""
        return f'<td class="num {cls}{faint}">{v}%</td>'

    sections = ""
    for title, sub, color, tickers, keys in GROUPS:
        rows = ""
        for tk in tickers:
            entries = [(k, stat(tk, k)) for k in keys]
            entries = [(k, s) for k, s in entries if s]     # 只列有触发的信号
            if not entries:
                rows += (f'<tr><td class="tk">{tk}</td><td class="nm">{NAMES[tk]}</td>'
                         f'<td class="mut" colspan="6">近5年无触发</td></tr>')
                continue
            for i, (k, s) in enumerate(entries):
                n, r5, r10, r20, avg20 = s
                lab, tier = SIG_LABEL[k]
                tkcell = (f'<td class="tk" rowspan="{len(entries)}">{tk}</td>'
                          f'<td class="nm" rowspan="{len(entries)}">{NAMES[tk]}</td>') if i == 0 else ""
                avgcls = "hi" if avg20 > 0 else "lo"
                rows += (f'<tr>{tkcell}'
                         f'<td class="sig {tier}">{lab}</td>'
                         f'<td class="num">{n}</td>'
                         f'{pct_td(r5, n)}{pct_td(r10, n)}{pct_td(r20, n)}'
                         f'<td class="num {avgcls}">{avg20:+.1f}%</td></tr>')
        sections += (f'<section><div class="gh" style="color:{color}">{title}'
                     f'<span class="gsub">{sub}</span></div>'
                     '<div class="tw"><table><thead><tr>'
                     '<th>代码</th><th>名称</th><th>信号</th><th class="num">触发次数</th>'
                     '<th class="num">5日涨率</th><th class="num">10日涨率</th><th class="num">20日涨率</th>'
                     '<th class="num">20日均值</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table></div></section>')

    asof = str(d["date"].max())[:10]
    html = TEMPLATE.replace("{{SECTIONS}}", sections).replace("{{ASOF}}", asof)
    (ROOT / "backtest_stats.html").write_text(html, encoding="utf-8")
    print(f"✅ backtest_stats.html 生成完毕（数据截至 {asof}）")


TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>买入/强买入信号 · 5年回溯查阅表</title>
<style>
  :root{--bg:#eef1f4;--card:#fff;--ink:#1a1d21;--muted:#8a9099;--line:#e4e8ec;--head:#f5f6f8;
    --hi:#12924f;--mid:#b7791f;--lo:#d92d20;--strong:#0b7a41;--buy:#12924f;--zebra:#fafbfc;}
  @media(prefers-color-scheme:dark){:root{--bg:#0d1015;--card:#161a20;--ink:#e6e9ee;--muted:#8b93a0;
    --line:#252b33;--head:#1c2129;--hi:#43d18f;--mid:#e0a53f;--lo:#ff6b60;--strong:#43d18f;--buy:#43d18f;--zebra:#141820;}}
  :root[data-theme="light"]{--bg:#eef1f4;--card:#fff;--ink:#1a1d21;--muted:#8a9099;--line:#e4e8ec;--head:#f5f6f8;
    --hi:#12924f;--mid:#b7791f;--lo:#d92d20;--strong:#0b7a41;--buy:#12924f;--zebra:#fafbfc;}
  :root[data-theme="dark"]{--bg:#0d1015;--card:#161a20;--ink:#e6e9ee;--muted:#8b93a0;--line:#252b33;--head:#1c2129;
    --hi:#43d18f;--mid:#e0a53f;--lo:#ff6b60;--strong:#43d18f;--buy:#43d18f;--zebra:#141820;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);line-height:1.5;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
    -webkit-font-smoothing:antialiased}
  .wrap{max-width:940px;margin:0 auto;padding:40px 18px 72px}
  .eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:700;margin:0 0 8px}
  h1{font-size:25px;font-weight:750;margin:0 0 10px;letter-spacing:.2px}
  .lede{font-size:14px;color:var(--muted);max-width:78ch;margin:0 0 8px;line-height:1.65}
  .lede b{color:var(--ink)}
  .asof{font-size:12.5px;color:var(--muted);margin:0 0 26px}
  section{margin-bottom:26px}
  .gh{font-size:17px;font-weight:700;margin:0 0 10px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
  .gsub{font-size:12px;font-weight:500;color:var(--muted)}
  .tw{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow-x:auto}
  table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
  th,td{padding:9px 12px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
  th{background:var(--head);font-size:12px;color:var(--muted);font-weight:600;position:sticky;top:0}
  th.num,td.num{text-align:right}
  tbody tr:last-child td{border-bottom:none}
  td.tk{font-weight:700;letter-spacing:.3px;border-right:1px solid var(--line)}
  td.nm{color:var(--muted);font-size:12.5px;border-right:1px solid var(--line)}
  td.sig{font-size:12.5px}
  td.sig.strong{color:var(--strong);font-weight:600}
  td.sig.buy{color:var(--buy)}
  td.hi{color:var(--hi);font-weight:600}
  td.mid{color:var(--mid);font-weight:600}
  td.lo{color:var(--lo);font-weight:600}
  td.faint{opacity:.5}
  td.mut,.mut{color:var(--muted)}
  .foot{margin-top:26px;font-size:12px;color:var(--muted);line-height:1.75;border-top:1px solid var(--line);padding-top:16px}
  .foot b{color:var(--ink)}
  code{background:var(--head);padding:1px 5px;border-radius:4px;font-size:12px}
</style></head><body>
<div class="wrap">
  <p class="eyebrow">买入 / 强买入信号 · 历史回溯</p>
  <h1>31 标的 · 5 年触发次数与 5/10/20 日反弹概率</h1>
  <p class="lede">按 <b>Tier2 分组</b>列出每个标的实际启用的买入/强买入信号:<b>触发次数</b> + 同一批信号在 <b>5日 / 10日 / 20日</b>三个持有期的<b>方向胜率</b>(信号日收盘 → N 个交易日后收盘,涨为对) + 20日平均收益。同批口径(以能算满20日为准)才能看出<b>反弹节奏</b>——如某标的"10日涨率" 明显低于 5日/20日,说明破位后往往先探底再拉起、中途难受。</p>
  <p class="lede"><b>怎么读</b>:胜率 <span style="color:var(--hi);font-weight:600">≥70% 绿</span> / <span style="color:var(--mid);font-weight:600">50–70% 琥珀</span> / <span style="color:var(--lo);font-weight:600">&lt;50% 红</span>;触发次数 <b>&lt;5 的行半透明</b>——小样本,胜率再高也只作"极端程度/方向"参考,别当 edge。NET/COIN 技术上无可靠抄底点、不列。</p>
  <p class="asof">数据截至 {{ASOF}} · 口径与工具/邮件/logic.html 完全一致</p>
  {{SECTIONS}}
  <div class="foot">
    <b>口径</b>　"涨率"= 固定持有期终点方向胜率(只看第 N 个交易日收盘 vs 信号日,不看中途路径/回撤);真正决定可交易性的是分组 <b>edge + 三重障碍盈亏比</b>(见 <code>logic.html</code>),此表的个股胜率是辅助佐证。<br>
    <b>样本独立性</b>　同一波回调里连续破位会连续触发、高度相关,"触发次数"高估独立事件数;叠加多数标的近年为上升趋势,小样本高胜率含较多 beta,审慎看待。<br>
    <b>数据源</b>　<code>output/model_dataset.csv</code>(近5年复权日线);重跑 <code>python gen_backtest_table.py</code> 更新。
  </div>
</div></body></html>"""


if __name__ == "__main__":
    main()
