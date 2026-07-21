#!/usr/bin/env python3
"""每日大机会告警——供 GitHub Actions 定时运行：拉 31 标的最新数据，检测买入/卖出信号，
有触发才推送(微信 Server酱 / 邮件)，无触发不打扰。

复用 build_dataset 的取数与指标逻辑，信号口径与工具 index.html、回测 edge_scanner 完全一致：
  🟢 强买入 RSI<20 / 买入 RSI<25（深度超卖，回溯高胜率）
  🟠 卖出   PE五年分位>95 且 RSI>70，仅非高波动股（HI_VOL 名单排除）

环境变量（GitHub Secrets）：
  MASSIVE_API_KEY     必填，Polygon/Massive key
  SERVERCHAN_SENDKEY  选填，微信 Server酱推送(sct.ftqq.com)
  SMTP_HOST/PORT/USER/PASS/TO  选填，邮件推送
  至少配一个通知渠道。
"""
import os
import sys

import pandas as pd

import build_dataset as bd   # 复用取数/指标/估值逻辑，口径一致

# 与 index.html / edge_scanner 一致的高波动名单：这些标的不出卖出信号(超买后倾向续涨)
HI_VOL = {"LEU", "COIN", "NET", "SNOW", "TSLA", "AMD", "GEV", "MU", "NVDA",
          "BABA", "CEG", "VST", "AVGO"}
NAMES = {
    "AAPL": "苹果", "MSFT": "微软", "GOOGL": "谷歌", "AMZN": "亚马逊", "NVDA": "英伟达",
    "META": "Meta", "TSLA": "特斯拉", "MCD": "麦当劳", "TSM": "台积电", "JPM": "摩根大通",
    "CEG": "星座能源", "AVGO": "博通", "BRK.B": "伯克希尔", "LEU": "Centrus", "LLY": "礼来",
    "AMD": "超微", "MU": "美光", "QCOM": "高通", "NET": "Cloudflare", "SNOW": "Snowflake",
    "VST": "Vistra", "NEE": "新纪元", "GEV": "GE Vernova", "CAT": "卡特彼勒", "COIN": "Coinbase",
    "BABA": "阿里", "GS": "高盛", "MS": "摩根士丹利", "QQQ": "纳指100", "SPY": "标普500", "SOXX": "半导体ETF",
}


def get_key() -> str:
    k = os.environ.get("MASSIVE_API_KEY")
    if not k:
        try:
            k = bd.load_api_key()   # 本地调试 fallback 到 config.js
        except Exception:
            pass
    if not k:
        sys.exit("❌ 缺 MASSIVE_API_KEY（GitHub Secrets 或本地 config.js）")
    return k


def latest_metrics(tk: str, is_etf: bool, key: str, s: str, e: str):
    bars = bd.fetch_daily_bars(tk, key, s, e)
    if bars.empty:
        return None
    splits = [] if is_etf else bd.fetch_splits(tk, key)
    bars = bd.drop_unreliable_price_regime(tk, bars, splits)
    df = bd.add_technical_indicators(bars)
    if not is_etf:
        fdf = bd.build_fundamentals_daily(bd.fetch_quarterly_financials(tk, key), splits)
        df = bd.add_fundamentals(df, fdf)
    else:
        df = bd.add_fundamentals(df, pd.DataFrame())
    last = df.iloc[-1]
    return {"date": str(last["date"]), "rsi": last["rsi14"],
            "pe_pctile": last.get("pe_percentile_causal")}


# 每组的标题/说明/主色(买入绿、卖出橙)
GROUP_META = {
    "strong": ("🟢 强买入", "RSI(14)&lt;20 极端超卖 · 回溯20日涨87% · 盈亏比9.8", "#12924f"),
    "buy":    ("🟢 买入",   "RSI(14)&lt;25 深度超卖 · 回溯20日涨79% · 盈亏比3.4", "#12924f"),
    "sell":   ("🟠 卖出/减仓参考", "PE五年分位&gt;95 且 RSI(14)&gt;70 · 仅非高波动股 · 非做空", "#b7791f"),
}


def build_messages(asof, groups):
    """groups: [(key, [(ticker,name,metric),...]), ...] → (markdown 给Server酱, HTML 给邮件)"""
    md = [f"数据截至 {asof}"]
    for key, items in groups:
        label, sub, _ = GROUP_META[key]
        md.append(f"**{label}**（{sub}）\n" + "\n".join(f"- {t} {n}：{m}" for t, n, m in items))
    md_txt = "\n\n".join(md).replace("&lt;", "<").replace("&gt;", ">")

    sections = ""
    for key, items in groups:
        label, sub, color = GROUP_META[key]
        rows = "".join(
            '<tr style="border-bottom:1px solid #eef0f2">'
            f'<td style="padding:8px 0;font-weight:600;font-size:14px">{t}</td>'
            f'<td style="padding:8px 10px;color:#8a9099;font-size:13px">{n}</td>'
            f'<td style="padding:8px 0;text-align:right;font-size:14px;color:#3a3f45">{m}</td></tr>'
            for t, n, m in items)
        sections += (f'<div style="margin-bottom:22px">'
                     f'<div style="font-weight:600;font-size:15px;color:{color}">{label}</div>'
                     f'<div style="color:#8a9099;font-size:12px;margin:3px 0 6px">{sub}</div>'
                     f'<table style="width:100%;border-collapse:collapse">{rows}</table></div>')
    html = ('<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,'
            'sans-serif;max-width:520px;margin:0 auto;padding:20px 18px;color:#1a1d21;background:#fff">'
            '<div style="font-size:19px;font-weight:700;letter-spacing:.3px">⚡ 股票大机会</div>'
            f'<div style="color:#8a9099;font-size:13px;margin:3px 0 24px">数据截至 {asof}</div>{sections}'
            '<div style="color:#aab0b8;font-size:11px;border-top:1px solid #eef0f2;padding-top:14px;'
            'line-height:1.7">规则来自 edge_scanner 对 31 标的近 5 年回溯：买入=历史高胜率抄底信号；'
            '卖出仅供止盈参考、<b>非做空</b>。RSI 为日线 14 周期（Wilder 平滑）。'
            '<br>本邮件由 GitHub Actions 自动发送，请勿回复。</div></div>')
    return md_txt, html


def main():
    if os.environ.get("ALERT_TEST") == "true":   # 发一封带示例数据的真实样式邮件，供预览
        sample = [("strong", [("NVDA", "英伟达", "RSI 18.5")]),
                  ("buy", [("TSM", "台积电", "RSI 23.1"), ("AAPL", "苹果", "RSI 24.4")]),
                  ("sell", [("GS", "高盛", "PE分位 98 · RSI 73")])]
        md, html = build_messages("示例数据（这是测试预览，非真实信号）", sample)
        notify("⚡股票大机会 · 样式预览（测试）", md, html)
        return

    key = get_key()
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=5)
    s, e = start.date().isoformat(), end.date().isoformat()

    strong_buy, buy, sell = [], [], []
    asof = None
    for tk, is_etf in bd.UNIVERSE:
        try:
            m = latest_metrics(tk, is_etf, key, s, e)
        except Exception as ex:
            print(f"[跳过] {tk}: {ex}")
            continue
        if not m or m["rsi"] is None:
            continue
        asof, rsi, pe = m["date"], m["rsi"], m["pe_pctile"]
        name = NAMES.get(tk, "")
        if rsi < 20:
            strong_buy.append((tk, name, f"RSI {rsi:.1f}"))
        elif rsi < 25:
            buy.append((tk, name, f"RSI {rsi:.1f}"))
        if (not is_etf) and tk not in HI_VOL and pe is not None and pe > 95 and rsi > 70:
            sell.append((tk, name, f"PE分位 {pe:.0f} · RSI {rsi:.1f}"))

    if not (strong_buy or buy or sell):
        print(f"数据截至 {asof}：今日无大机会信号，不推送。")
        return

    groups = [(k, v) for k, v in [("strong", strong_buy), ("buy", buy), ("sell", sell)] if v]
    title = "⚡股票大机会 " + "·".join(filter(None, [
        f"强买{len(strong_buy)}" if strong_buy else "",
        f"买入{len(buy)}" if buy else "",
        f"卖出{len(sell)}" if sell else ""]))
    md, html = build_messages(asof, groups)
    print(title + "\n" + md)
    notify(title, md, html)


def notify(title: str, md: str, html: str):
    sent = []
    sk = os.environ.get("SERVERCHAN_SENDKEY")
    if sk:
        import requests
        r = requests.post(f"https://sctapi.ftqq.com/{sk}.send",
                          data={"title": title, "desp": md}, timeout=20)
        sent.append(f"Server酱 {r.status_code}")
    if os.environ.get("SMTP_HOST"):
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header
        msg = MIMEText(html, "html", "utf-8")            # HTML 邮件
        msg["Subject"] = str(Header(title, "utf-8"))     # 中文/emoji 标题需编码，否则乱码
        msg["From"], msg["To"] = os.environ["SMTP_USER"], os.environ["SMTP_TO"]
        with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 465))) as srv:
            srv.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            srv.send_message(msg)
        sent.append("邮件")
    print("已推送：" + ("、".join(sent) if sent else "⚠️ 未配置任何通知渠道(SERVERCHAN_SENDKEY / SMTP_*)"))


if __name__ == "__main__":
    sys.exit(main())
