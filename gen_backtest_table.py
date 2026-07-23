#!/usr/bin/env python3
"""生成「31 标的 · 买入/强买入信号历史回溯」查阅表 → backtest_stats.html（GitHub Pages 可访问）。

口径与 build_ticker_stats / daily_alert 完全一致：近5年日线，同一批信号(以能算满20日为准)看
5日/10日/20日三个持有期的方向胜率(收盘价 vs 信号日收盘，涨为对)。按 Tier2 分组组织。
数据源：output/model_dataset.csv（build_dataset→build_labels 生成）。重跑：python gen_backtest_table.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "output" / "model_dataset.csv"


def wilson_lb(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d

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
def main():
    d = pd.read_csv(DATA).sort_values(["ticker", "date"]).reset_index(drop=True)
    for h in (5, 10, 20):
        d[f"fwd{h}"] = d.groupby("ticker")["close"].shift(-h) / d["close"] - 1
    CFG = json.loads((ROOT / "signal_config.json").read_text(encoding="utf-8"))
    for N in {cfg["boll"][k] for cfg in CFG.values() for k in ("s", "b") if cfg["boll"][k]}:
        ma = d.groupby("ticker")["close"].transform(lambda s: s.rolling(N).mean())
        sd = d.groupby("ticker")["close"].transform(lambda s: s.rolling(N).std())
        d[f"boll{N}"] = d.close <= ma - 2 * sd
    d = d[d["fwd20"].notna()].copy()

    def stat(tk, mask):
        s = d[(d.ticker == tk) & mask.fillna(False)]
        n = len(s)
        if not n:
            return None
        lb = wilson_lb(int((s.fwd20 > 0).sum()), n)
        return (n, *[round((s[f"fwd{h}"] > 0).mean() * 100) for h in (5, 10, 20)],
                round(lb * 100), s["fwd20"].mean() * 100)

    def sigs_for(tk):
        """该标的的信号档：per-ticker 校准的 RSI 阈值 + 布林周期(signal_config)。无档标的返回空→无信号。"""
        cfg = CFG.get(tk)
        out = []
        if cfg:
            if cfg["rsi"]["s"]:
                out.append((f"强买入 · RSI(14)&lt;{cfg['rsi']['s']}", "strong", d.rsi14 < cfg["rsi"]["s"]))
            if cfg["rsi"]["b"]:
                out.append((f"买入 · RSI(14)&lt;{cfg['rsi']['b']}", "buy", d.rsi14 < cfg["rsi"]["b"]))
            if cfg["boll"]["s"]:
                out.append((f"强买入 · 破 {cfg['boll']['s']} 日布林下轨", "strong", d[f"boll{cfg['boll']['s']}"]))
            if cfg["boll"]["b"]:
                out.append((f"买入 · 破 {cfg['boll']['b']} 日布林下轨", "buy", d[f"boll{cfg['boll']['b']}"]))
        return out

    def src(tk):
        cfg = CFG.get(tk)
        if not cfg:
            return 3
        has_r = bool(cfg["rsi"]["s"] or cfg["rsi"]["b"])
        has_b = bool(cfg["boll"]["s"] or cfg["boll"]["b"])
        return 0 if (has_r and has_b) else (1 if has_r else 2)

    GROUPS = [
        ("🎯 RSI + 布林 双源", "两类信号都有校准档", "#4f46e5", [t for t in NAMES if src(t) == 0]),
        ("📉 仅 RSI 档", "RSI 阈值 per-ticker 校准", "#12924f", [t for t in NAMES if src(t) == 1]),
        ("〽️ 仅布林档", "布林周期 per-ticker 校准", "#b45309", [t for t in NAMES if src(t) == 2]),
    ]

    def pct_td(v, n):
        cls = "hi" if v >= 70 else "mid" if v >= 50 else "lo"
        faint = " faint" if n < 5 else ""
        return f'<td class="num {cls}{faint}">{v}%</td>'

    sections = ""
    for title, sub, color, tickers in GROUPS:
        rows = ""
        for tk in tickers:
            entries = [(lab, tier, stat(tk, mask)) for lab, tier, mask in sigs_for(tk)]
            entries = [(lab, tier, s) for lab, tier, s in entries if s]     # 只列有触发的信号
            if not entries:
                rows += (f'<tr><td class="tk">{tk}</td><td class="nm">{NAMES[tk]}</td>'
                         f'<td class="mut" colspan="7">近5年无触发</td></tr>')
                continue
            for i, (lab, tier, s) in enumerate(entries):
                n, r5, r10, r20, lb, avg20 = s
                tkcell = (f'<td class="tk" rowspan="{len(entries)}">{tk}</td>'
                          f'<td class="nm" rowspan="{len(entries)}">{NAMES[tk]}</td>') if i == 0 else ""
                avgcls = "hi" if avg20 > 0 else "lo"
                lbcls = "hi" if lb >= 60 else "mid" if lb >= 50 else "lo"
                rows += (f'<tr>{tkcell}'
                         f'<td class="sig {tier}">{lab}</td>'
                         f'<td class="num">{n}</td>'
                         f'{pct_td(r5, n)}{pct_td(r10, n)}{pct_td(r20, n)}'
                         f'<td class="num {lbcls}">{lb}%</td>'
                         f'<td class="num {avgcls}">{avg20:+.1f}%</td></tr>')
        sections += (f'<section><div class="gh" style="color:{color}">{title}'
                     f'<span class="gsub">{sub}</span></div>'
                     '<div class="tw"><table><thead><tr>'
                     '<th>代码</th><th>名称</th><th>信号</th><th class="num">触发</th>'
                     '<th class="num">5日</th><th class="num">10日</th><th class="num">20日</th>'
                     '<th class="num">20日下界</th><th class="num">20日均值</th></tr></thead>'
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
  <p class="lede"><b>per-ticker 信号校准</b>:每只标的用自己近5年数据,定制 <b>RSI 阈值</b> 和 <b>布林下轨周期</b>。判定用<b>原始胜率(多持有期达标)</b>——<b>强买入</b>:5/10/20日里 ≥2个&gt;95% 且 三个都&gt;55%;<b>买入</b>:≥2个&gt;80% 且 三个都&gt;55%。理念:<b>N 小=极端罕见=大机会</b>,不用重罚小样本的 Wilson 下界当门槛。26 只有档、按信号来源(RSI+布林/仅RSI/仅布林)分组;<b>5 只无信号(AMD/BABA/COIN/MS/TSM)诚实留空、不列</b>。</p>
  <p class="lede">列含<b>触发次数 + 5/10/20日方向胜率 + 20日 Wilson 下界</b>(仅供参考,不是门槛) + 20日平均收益。固定100布林/dip(破日线下轨+MA200)/均线支撑经测试均不达标、已弃。<b>⚠️ 阈值在同份数据上选+评估,有过拟合乐观偏差,小样本高胜率作"极端信号提示"、别当可交易 edge,实盘打折。</b></p>
  <p class="lede"><b>怎么读</b>:胜率/下界 <span style="color:var(--hi);font-weight:600">≥70/≥60 绿</span> / <span style="color:var(--mid);font-weight:600">中档琥珀</span> / <span style="color:var(--lo);font-weight:600">低 红</span>;触发次数 <b>&lt;5 的行半透明</b>——小样本、极端罕见,由 N 自证。</p>
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
