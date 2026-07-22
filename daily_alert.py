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
import time

import pandas as pd

import build_dataset as bd   # 复用取数/指标/估值逻辑，口径一致

# 与 index.html / edge_scanner 一致的高波动名单：这些标的不出卖出信号(超买后倾向续涨)
HI_VOL = {"LEU", "COIN", "NET", "SNOW", "TSLA", "AMD", "GEV", "MU", "NVDA",
          "BABA", "CEG", "VST", "AVGO"}
# 动量组 Tier2 三档：趋势回调(破日线下轨+ma200) / 大级别支撑(破100日布林) / 无信号(NET,COIN)
MOM_DIP = {"NVDA", "AVGO", "MU", "AMD", "GEV", "CEG", "LEU", "VST"}
MOM_BIG = {"SNOW", "TSLA", "BABA"}

def fmt_tstat(s):
    """格式化实时算出的个股回溯 [N, 涨率%]。N 小(甚至=1)也保留：反映该信号在该股极罕见=极端。"""
    if not s or s[0] == 0:
        return "本标的0次(极罕见)"
    return f"本标的{s[0]}次涨{s[1]}%"
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
    # 日线(买入信号核心，仅 2 个请求)：加重试，尽量拿到
    for attempt in range(3):
        try:
            bars = bd.fetch_daily_bars(tk, key, s, e)
            if bars.empty:
                return None
            splits = [] if is_etf else bd.fetch_splits(tk, key)
            break
        except Exception:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    bars = bd.drop_unreliable_price_regime(tk, bars, splits)
    df = bd.add_technical_indicators(bars)
    # 财报(仅卖出信号用 PE 分位，请求多、是限速主因)：失败就跳过，绝不拖累买入信号
    if not is_etf:
        try:
            fdf = bd.build_fundamentals_daily(bd.fetch_quarterly_financials(tk, key), splits)
            df = bd.add_fundamentals(df, fdf)
        except Exception:
            df = bd.add_fundamentals(df, pd.DataFrame())   # PE 列 NaN → 卖出不触发，买入照常
    else:
        df = bd.add_fundamentals(df, pd.DataFrame())
    last = df.iloc[-1]
    ma200 = last.get("ma200")
    c = df["close"]
    m100s, s100s = c.rolling(100).mean(), c.rolling(100).std()
    # 实时算该标的历史个股率[N,涨率%]（用已拉的 5 年 df 当场算，永远最新、免维护）
    up = df["fwd_ret_20d"] > 0
    valid = df["fwd_ret_20d"].notna()

    def pstat(mask):
        mm = (mask & valid).fillna(False)
        n = int(mm.sum())
        return [n, round(up[mm].mean() * 100)] if n else [0, None]

    tstats = {
        "rsi20": pstat(df["rsi14"] < 20),
        "rsi25": pstat(df["rsi14"] < 25),
        "b100": pstat(c <= m100s - 2 * s100s),
        "dip": pstat((df["boll_pctb"] < 0) & (df["close"] > df["ma200"])),
    }
    return {"date": str(last["date"]), "rsi": last["rsi14"],
            "pe_pctile": last.get("pe_percentile_causal"),
            "pctB": last.get("boll_pctb"),
            "above_ma200": bool(pd.notna(ma200) and last["close"] > ma200),
            "below100": bool(pd.notna(m100s.iloc[-1]) and last["close"] <= m100s.iloc[-1] - 2 * s100s.iloc[-1]),
            "tstats": tstats}


# 每组的标题/说明/主色(买入绿、卖出橙)
GROUP_META = {
    "strong": ("🟢 强买入", "稳健股 RSI(14)&lt;20 极端超卖 · 回溯涨88% · 下界70%", "#12924f"),
    "buy":    ("🟢 买入",   "稳健股 RSI(14)&lt;25 · 动量·趋势回调组 破下轨且价ma200上 · 大级别支撑组(SNOW/TSLA/BABA) 破100日布林", "#12924f"),
    "sell":   ("🟠 卖出/减仓参考", "PE五年分位&gt;95 且 RSI(14)&gt;70 · 仅稳健股 · 非做空", "#b7791f"),
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
    if os.environ.get("ALERT_TEST") == "true":   # 仅当手动勾选 test 框时：发样式预览，不做实际检测
        print("【测试模式】ALERT_TEST=true → 只发样式预览邮件，未做任何实际信号检测")
        sample = [("strong", [("AAPL", "苹果", "RSI(14) 18.5")]),
                  ("buy", [("MSFT", "微软", "RSI(14) 23.1"), ("NVDA", "英伟达", "破布林下轨·价在MA200上"),
                           ("TSLA", "特斯拉", "破100日布林下轨(大支撑)")]),
                  ("sell", [("GS", "高盛", "PE分位 98 · RSI(14) 73")])]
        md, html = build_messages("示例数据（这是测试预览，非真实信号）", sample)
        notify("⚡股票大机会 · 样式预览（测试）", md, html)
        return

    key = get_key()
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=5)
    s, e = start.date().isoformat(), end.date().isoformat()

    print(f"【生产模式】实际检测 {len(bd.UNIVERSE)} 个标的的大机会信号…")
    strong_buy, buy, sell = [], [], []
    asof = None
    n_fail = 0
    for tk, is_etf in bd.UNIVERSE:
        time.sleep(0.4)                  # 标的间降频，避免瞬时触发限速
        try:
            m = latest_metrics(tk, is_etf, key, s, e)
        except Exception as ex:
            print(f"[跳过] {tk}: {ex}")
            n_fail += 1
            continue
        if not m or m["rsi"] is None:
            n_fail += 1
            continue
        asof, rsi, pe = m["date"], m["rsi"], m["pe_pctile"]
        name = NAMES.get(tk, "")
        if tk in HI_VOL:                 # 动量组 Tier2 三档
            if tk in MOM_DIP:            # 趋势回调：破日线布林下轨 且 价在 MA200 上
                if m["pctB"] is not None and m["pctB"] < 0 and m["above_ma200"]:
                    buy.append((tk, name, f"破布林下轨·价在MA200上｜{fmt_tstat(m['tstats']['dip'])}"))
            elif tk in MOM_BIG:         # 大级别支撑：破 100 日布林下轨
                if m["below100"]:
                    buy.append((tk, name, f"破100日布林下轨(大支撑)｜{fmt_tstat(m['tstats']['b100'])}"))
            # NET/COIN：无可靠信号，不触发
        else:                            # 稳健组：RSI(14) 超卖 或 破100日布林(大级别支撑)
            if rsi < 20:
                strong_buy.append((tk, name, f"RSI(14) {rsi:.1f}｜{fmt_tstat(m['tstats']['rsi20'])}"))
            elif rsi < 25:
                buy.append((tk, name, f"RSI(14) {rsi:.1f}｜{fmt_tstat(m['tstats']['rsi25'])}"))
            elif m["below100"]:          # RSI 未触发但破100日布林下轨
                buy.append((tk, name, f"破100日布林下轨(大支撑)｜{fmt_tstat(m['tstats']['b100'])}"))
            if pe is not None and pe > 95 and rsi > 70:   # 卖出仅稳健组
                sell.append((tk, name, f"PE分位 {pe:.0f}·RSI(14) {rsi:.1f}"))

    if n_fail > 3:   # 拉取失败过多(可能云端限速)：明确告警，绝不静默漏报
        warn = f"本次 {n_fail}/{len(bd.UNIVERSE)} 个标的数据拉取失败(疑似限速)，未完整检测、可能漏报信号，请留意。"
        notify("⚠️ 大机会告警·数据不全", warn, f'<div style="font-family:sans-serif;padding:12px;color:#b7791f">{warn}</div>')
        print("⚠️ " + warn)

    if not (strong_buy or buy or sell):
        print(f"数据截至 {asof}：今日无大机会信号（失败 {n_fail} 只），不推送。")
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
