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


def detect_earnings_landmine(df, fin):
    """判断"触发买入的这次下跌是不是财报暴雷砸的坑"。
    回溯验证：近15天内有财报日 且 财报当日/次日出现大阴线(单日<-6%)的买入信号，20日涨率仅62%
    (下界52%)，明显差于温和回落/远离财报的71%——是接飞刀。据此对买入信号打红旗。
    返回 None=无财报数据(不判断)；{'landmine':bool,...}。财报日精确度：季报(10-Q)准，
    年报季(10-K)filing_date 常缺→用 end_date+50天近似，标记 approx。"""
    if not fin:
        return None
    ev = []                                          # (财报日, 是否近似)
    for f in fin:
        fd = f.get("filing_date") or (f.get("acceptance_datetime") or "")[:10]
        approx = False
        if not fd:
            fd = (pd.Timestamp(f["end_date"]) + pd.Timedelta(days=50)).date().isoformat()
            approx = True
        ev.append((pd.Timestamp(fd), approx))
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ret1"] = d["close"].pct_change()
    last_date = d["date"].iloc[-1]
    past = [(fd, ap) for fd, ap in ev if fd <= last_date]
    if not past:
        return None
    fd, approx = max(past, key=lambda x: x[0])       # 最近一次财报
    dse, latest = int((last_date - fd).days), fd.date().isoformat()
    if dse > 15:
        # 近15天无财报→当前下跌与财报无关。但若距最近已知财报 >85天(≈一个季度)，说明下一季
        # 财报可能已发布但数据源尚未入库(Starter 无前瞻财报日历)→ stale，供买入信号附中性核对提示
        return {"landmine": False, "dse": dse, "latest_filing": latest, "stale": dse > 85}
    # 财报日附近[-1,+2 交易日]的最差单日收益(用日历窗口兜住周末/盘后发次日反应)
    win = d[(d["date"] >= fd - pd.Timedelta(days=4)) & (d["date"] <= fd + pd.Timedelta(days=6))]
    worst = win["ret1"].min()
    if pd.isna(worst):
        return None
    return {"landmine": bool(worst < -0.06), "worst": float(worst),
            "dse": dse, "latest_filing": latest, "approx": approx, "stale": False}


def landmine_tag(m):
    """买入信号的财报事件标注：
    ①真雷区(财报大阴线)→红旗⚠️；②财报数据可能滞后一季(stale)→中性核对提示ℹ️(不改判断、不误伤)。"""
    lm = m.get("landmine")
    if not lm:
        return ""
    if lm.get("landmine"):
        sfx = "近似" if lm.get("approx") else ""
        return f"｜⚠️财报暴雷坑{sfx}(距财报{lm['dse']}天·当日{lm['worst']*100:.0f}%·历史62%,慎接飞刀)"
    if lm.get("stale"):    # 前瞻财报日历数据源不给，只能提醒：可能刚发财报未入库，请自行核对
        return f"｜ℹ️财报数据仅到{lm['latest_filing']}({lm['dse']}天前)，该标的可能刚发新财报尚未入库，请核对是否财报暴雷再决定"
    return ""
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
    # 财报(卖出信号用 PE 分位 + 事件闸门算"财报暴雷坑/数据滞后提示"，同一次请求)：失败就跳过，绝不拖累买入信号
    # 关键：限速常见"200+空results"(非抛异常)，空 list 必须视同请求失败(不重试、省 API)，否则会静默漏掉提示
    landmine, fin = None, None
    if not is_etf:
        try:
            fin = bd.fetch_quarterly_financials(tk, key)
        except Exception:
            fin = None
        if fin:                                  # 非空才算真拿到；空/失败一律走下面的降级分支
            try:
                df = bd.add_fundamentals(df, bd.build_fundamentals_daily(fin, splits))
                landmine = detect_earnings_landmine(df, fin)   # 用同一批财报的 filing_date 判雷区/滞后
            except Exception as ex:
                df = bd.add_fundamentals(df, pd.DataFrame())
                print(f"[财报处理异常] {tk}: {type(ex).__name__}: {ex}")
        else:
            df = bd.add_fundamentals(df, pd.DataFrame())       # PE 列 NaN → 卖出不触发，买入照常；landmine 留 None
            print(f"[财报未拉到] {tk}: 疑似限速(空结果/请求失败)，本次无 PE 分位与事件闸门提示")
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
            "tstats": tstats, "landmine": landmine}


# 每组的标题/说明/主色(买入绿、卖出橙)
GROUP_META = {
    "strong": ("🟢 强买入", "稳健股 RSI(14)&lt;20 极端超卖 · 回溯涨88% · 下界70%", "#12924f"),
    "buy":    ("🟢 买入",   "深度超卖抄底信号 · 各标的所属分组见标签", "#12924f"),
    "sell":   ("🟠 卖出/减仓参考", "PE五年分位&gt;95 且 RSI(14)&gt;70 · 仅稳健股 · 非做空", "#b7791f"),
}


def group_label(tk):
    """标的所属分组(与 index.html/logic.html 一致) → (标签文字, 背景色, 文字色)。"""
    if tk in MOM_DIP:  return "趋势回调组", "#eef2ff", "#4f46e5"
    if tk in MOM_BIG:  return "大级别支撑组", "#fef3c7", "#b45309"
    return "稳健组", "#f1f3f6", "#5a6270"


def _bullet_style(i, text, main_color):
    """每条 bullet 的圆点色/文字色/字号：首条=信号描述(主色醒目)，其余按内容分类降噪。"""
    if i == 0:                       return main_color, "#3a3f45", "13.5px"
    if text.startswith("⚠️"):        return "#c0392b", "#c0392b", "12.5px"   # 财报暴雷坑
    if text.startswith("ℹ️"):        return "#c3c8ce", "#8a6d3b", "12.5px"   # 财报数据滞后·中性提示
    return "#c3c8ce", "#8a9099", "12.5px"                                    # 个股回溯率等


def build_messages(asof, groups):
    """groups: [(key, [(ticker,name,metric),...]), ...] → (markdown 给Server酱, HTML 给邮件)。
    metric 用 ｜ 分隔多段(信号描述｜个股率｜财报提示…) → 渲染成 bullet 分列 + 标的组别标签。"""
    # ---- markdown（微信 Server酱）：嵌套 bullet ----
    md = [f"数据截至 {asof}"]
    for key, items in groups:
        label, _, _ = GROUP_META[key]
        lines = [f"**{label}**"]
        for t, n, m in items:
            lines.append(f"- **{t}** {n}（{group_label(t)[0]}）")
            for p in [x.strip() for x in m.split("｜") if x.strip()]:
                lines.append(f"  - {p}")
        md.append("\n".join(lines))
    md_txt = "\n\n".join(md).replace("&lt;", "<").replace("&gt;", ">")

    # ---- HTML（邮件）：每标的一个 block，bullet 分列 + 组别标签 ----
    sections = ""
    for key, items in groups:
        label, sub, color = GROUP_META[key]
        blocks = ""
        for t, n, m in items:
            gl, gbg, gfg = group_label(t)
            parts = [x.strip() for x in m.split("｜") if x.strip()]
            rows = ""
            for i, p in enumerate(parts):
                dot, txtcol, fs = _bullet_style(i, p, color)
                rows += ('<tr>'
                         f'<td style="vertical-align:top;color:{dot};padding:1px 8px 1px 0;font-size:13px">•</td>'
                         f'<td style="font-size:{fs};color:{txtcol};padding:1px 0;line-height:1.5">{p}</td></tr>')
            blocks += ('<div style="padding:12px 0;border-top:1px solid #eef0f2">'
                       '<div style="margin-bottom:7px">'
                       f'<span style="font-weight:700;font-size:15px">{t}</span>'
                       f'<span style="color:#8a9099;font-size:13px;margin-left:6px">{n}</span>'
                       f'<span style="display:inline-block;margin-left:8px;padding:1px 8px;border-radius:4px;'
                       f'background:{gbg};color:{gfg};font-size:11px;font-weight:600;vertical-align:middle">{gl}</span>'
                       '</div>'
                       f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse">{rows}</table></div>')
        sections += (f'<div style="margin-bottom:18px">'
                     f'<div style="font-weight:700;font-size:15px;color:{color}">{label}</div>'
                     f'<div style="color:#8a9099;font-size:12px;margin:2px 0 2px">{sub}</div>'
                     f'{blocks}</div>')
    html = ('<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,'
            'sans-serif;max-width:560px;margin:0 auto;padding:22px 20px;color:#1a1d21;background:#fff">'
            '<div style="font-size:20px;font-weight:700;letter-spacing:.3px">⚡ 自选股机会信号</div>'
            f'<div style="color:#8a9099;font-size:13px;margin:4px 0 22px">数据截至 {asof}</div>{sections}'
            '<div style="color:#aab0b8;font-size:11px;border-top:1px solid #eef0f2;padding-top:14px;'
            'line-height:1.7">规则来自 edge_scanner 对 31 标的近 5 年回溯：买入=历史高胜率抄底信号；'
            '卖出仅供止盈参考、<b>非做空</b>。RSI 为日线 14 周期（Wilder 平滑）。'
            '<br>本邮件由 GitHub Actions 自动发送，请勿回复。</div></div>')
    return md_txt, html


def main():
    if os.environ.get("ALERT_TEST") == "true":   # 仅当手动勾选 test 框时：发样式预览，不做实际检测
        print("【测试模式】ALERT_TEST=true → 只发样式预览邮件，未做任何实际信号检测")
        sample = [("strong", [("AAPL", "苹果", "RSI(14) 18.5｜本标的3次涨100%")]),
                  ("buy", [("MSFT", "微软", "RSI(14) 23.1｜本标的12次涨86%"),
                           ("GEV", "GE Vernova", "破布林下轨·价在MA200上｜本标的10次涨100%｜ℹ️财报数据仅到2026-04-22(91天前)，可能刚发新财报未入库，请核对是否财报暴雷"),
                           ("MU", "美光", "RSI(14) 24.0｜本标的5次涨80%｜⚠️财报暴雷坑(距财报6天·当日-9%·历史62%,慎接飞刀)"),
                           ("TSLA", "特斯拉", "破100日布林下轨(大支撑)｜本标的8次涨75%")]),
                  ("sell", [("GS", "高盛", "PE分位 98·RSI(14) 73")])]
        md, html = build_messages("示例数据（这是测试预览，非真实信号）", sample)
        notify("⚡自选股机会信号提示 · 样式预览（测试）", md, html)
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
        lm = landmine_tag(m)             # 事件闸门：这次下跌若是财报暴雷砸的，给买入信号挂红旗
        if tk in HI_VOL:                 # 动量组 Tier2 三档
            if tk in MOM_DIP:            # 趋势回调：破日线布林下轨 且 价在 MA200 上
                if m["pctB"] is not None and m["pctB"] < 0 and m["above_ma200"]:
                    buy.append((tk, name, f"破布林下轨·价在MA200上｜{fmt_tstat(m['tstats']['dip'])}{lm}"))
            elif tk in MOM_BIG:         # 大级别支撑：破 100 日布林下轨
                if m["below100"]:
                    buy.append((tk, name, f"破100日布林下轨(大支撑)｜{fmt_tstat(m['tstats']['b100'])}{lm}"))
            # NET/COIN：无可靠信号，不触发
        else:                            # 稳健组：RSI(14) 超卖 或 破100日布林(大级别支撑)
            if rsi < 20:
                strong_buy.append((tk, name, f"RSI(14) {rsi:.1f}｜{fmt_tstat(m['tstats']['rsi20'])}{lm}"))
            elif rsi < 25:
                buy.append((tk, name, f"RSI(14) {rsi:.1f}｜{fmt_tstat(m['tstats']['rsi25'])}{lm}"))
            elif m["below100"]:          # RSI 未触发但破100日布林下轨
                buy.append((tk, name, f"破100日布林下轨(大支撑)｜{fmt_tstat(m['tstats']['b100'])}{lm}"))
            if pe is not None and pe > 95 and rsi > 70:   # 卖出仅稳健组
                sell.append((tk, name, f"PE分位 {pe:.0f}·RSI(14) {rsi:.1f}"))

    if n_fail > 3:   # 拉取失败过多(可能云端限速)：明确告警，绝不静默漏报
        warn = f"本次 {n_fail}/{len(bd.UNIVERSE)} 个标的数据拉取失败(疑似限速)，未完整检测、可能漏报信号，请留意。"
        notify("⚠️ 自选股机会信号·数据不全", warn, f'<div style="font-family:sans-serif;padding:12px;color:#b7791f">{warn}</div>')
        print("⚠️ " + warn)

    if not (strong_buy or buy or sell):
        print(f"数据截至 {asof}：今日无大机会信号（失败 {n_fail} 只），不推送。")
        return

    groups = [(k, v) for k, v in [("strong", strong_buy), ("buy", buy), ("sell", sell)] if v]
    n_buy, n_sell = len(strong_buy) + len(buy), len(sell)   # 强买入并入买入计数（正文仍分组）
    title = "⚡自选股机会信号提示：" + "·".join(filter(None, [
        f"买入{n_buy}" if n_buy else "",
        f"卖出{n_sell}" if n_sell else ""]))
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
