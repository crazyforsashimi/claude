# -*- coding: utf-8 -*-
"""
Kindle 行情仪表盘生成器
------------------------------------------------------------------
用 Massive/Polygon 拉取 6 个标的的当日分钟级行情，渲染成一个「纯静态、零 JS」
的 HTML（内联 SVG 迷你走势图），供 Kindle 实验版浏览器定时刷新显示。

设计要点（针对灰度墨水屏）：
- 纯黑白高对比，涨跌用 ▲/▼ 箭头 + 正负号表达，不依赖颜色
- 所有数据烤进 HTML，Kindle 端不跑任何 JS、不暴露 API key
- <meta refresh> 让 Kindle 每 15 分钟自动重载（与数据延迟同步，减少墨水屏刷屏）

由 GitHub Actions 定时运行，把 kindle/index.html 提交回仓库，经 Pages 托管。
"""
import os
import json
import urllib.request
import datetime
from zoneinfo import ZoneInfo

# ---- 配置 -------------------------------------------------------
TICKERS = ["QQQ", "SPY", "NVDA", "GOOGL", "AAPL", "MSFT"]  # 想改标的就动这里
BASE = "https://api.massive.com"
KEY = os.environ.get("MASSIVE_API_KEY", "").strip()
ET = ZoneInfo("America/New_York")
OUT = os.path.join(os.path.dirname(__file__), "kindle", "index.html")

if not KEY:
    raise SystemExit("缺少 MASSIVE_API_KEY 环境变量")


def get(path):
    url = f"{BASE}{path}{'&' if '?' in path else '?'}apiKey={KEY}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def fetch(ticker):
    """返回 (last, prev_close, [(bar时间ET, close), ...], 数据时间戳ET)。失败抛异常。"""
    now_et = datetime.datetime.now(ET)
    frm = (now_et - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    to = now_et.strftime("%Y-%m-%d")
    data = get(f"/v2/aggs/ticker/{ticker}/range/5/minute/{frm}/{to}"
               f"?adjusted=true&sort=asc&limit=50000")
    bars = data.get("results") or []
    if not bars:
        raise ValueError("无 intraday 数据")

    # 只保留美东常规交易时段 09:30–16:00，按 ET 日期分组
    sessions = {}
    for b in bars:
        t = datetime.datetime.fromtimestamp(b["t"] / 1000, ET)
        mins = t.hour * 60 + t.minute
        if 9 * 60 + 30 <= mins <= 16 * 60:
            sessions.setdefault(t.date(), []).append((t, b["c"]))

    days = sorted(sessions.keys())
    if not days:
        raise ValueError("无常规时段数据")

    cur = sessions[days[-1]]           # [(bar时间ET, close), ...]
    last = cur[-1][1]
    stamp = cur[-1][0]                 # 最新一根 bar 的 ET 时间

    if len(days) >= 2:
        prev_close = sessions[days[-2]][-1][1]
    else:
        prev_close = cur[0][1]

    return last, prev_close, cur, stamp


SESSION_START = 9 * 60 + 30   # 09:30 ET
SESSION_LEN = 6 * 60 + 30     # 09:30–16:00 = 390 分钟


def sparkline(bars, prev_close, w=320, h=96, pad=8):
    """bars = [(bar时间ET, close), ...]。X 轴固定代表整个交易日，线随盘中推进从左往右生长。"""
    closes = [c for _, c in bars]
    vals = closes + [prev_close]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1

    def Xt(t):
        frac = ((t.hour * 60 + t.minute) - SESSION_START) / SESSION_LEN
        frac = min(1.0, max(0.0, frac))          # 越界夹到 [0,1]
        return pad + (w - 2 * pad) * frac

    def Y(v):
        return pad + (h - 2 * pad) * (1 - (v - lo) / (hi - lo))

    pts = " ".join(f"{Xt(t):.1f},{Y(c):.1f}" for t, c in bars)
    yb = Y(prev_close)
    ex, ey = Xt(bars[-1][0]), Y(bars[-1][1])     # 当前位置的小圆点
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{pad}" y1="{yb:.1f}" x2="{w-pad}" y2="{yb:.1f}" '
        f'stroke="#000" stroke-width="1" stroke-dasharray="4 3" opacity="0.45"/>'
        f'<polyline points="{pts}" fill="none" stroke="#000" '
        f'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3.5" fill="#000"/>'
        f'</svg>'
    )


_latest_stamp = [None]  # 记录所有标的中最新的一根 bar 时间，用于表头


def card(ticker):
    try:
        last, prev, bars, stamp = fetch(ticker)
        if _latest_stamp[0] is None or stamp > _latest_stamp[0]:
            _latest_stamp[0] = stamp
        chg = last - prev
        pct = chg / prev * 100 if prev else 0
        up = chg >= 0
        arrow = "&#9650;" if up else "&#9660;"  # ▲ / ▼
        sign = "+" if up else "-"
        price = f"{last:,.2f}"
        change = f"{arrow} {sign}{abs(chg):,.2f}  {sign}{abs(pct):.2f}%"
        spark = sparkline(bars, prev)
        cls = "up" if up else "down"
    except Exception as e:
        price = "&mdash;"
        change = f"数据获取失败"
        spark = '<svg class="spark" viewBox="0 0 320 96"></svg>'
        cls = "err"
        print(f"[warn] {ticker}: {e}")

    return (
        f'<div class="card {cls}">'
        f'<div class="row"><span class="sym">{ticker}</span>'
        f'<span class="price">{price}</span></div>'
        f'<div class="chg">{change}</div>'
        f'{spark}'
        f'</div>'
    )


def build():
    cards = "\n".join(card(t) for t in TICKERS)
    stamp = _latest_stamp[0] or datetime.datetime.now(ET)
    updated = stamp.strftime("%m-%d %H:%M ET")
    html = TEMPLATE.format(cards=cards, updated=updated)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] 写入 {OUT}")


TEMPLATE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Kindle 行情</title>
<style>
  html {{ -webkit-text-size-adjust: 100%; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #fff; color: #000;
    font-family: -apple-system, Helvetica, Arial, sans-serif;
    padding: 14px;
    -webkit-font-smoothing: none;
  }}
  header {{
    display: flex; justify-content: space-between; align-items: baseline;
    border-bottom: 3px solid #000; padding-bottom: 8px; margin-bottom: 12px;
  }}
  header h1 {{ font-size: 30px; letter-spacing: 2px; }}
  header .meta {{ font-size: 15px; }}
  .grid {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  }}
  .card {{
    border: 2px solid #000; border-radius: 6px; padding: 10px 12px 8px;
  }}
  .row {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .sym {{ font-size: 30px; font-weight: 800; letter-spacing: 1px; }}
  .price {{ font-size: 30px; font-weight: 700; }}
  .chg {{ font-size: 19px; font-weight: 700; margin: 4px 0 6px; }}
  .card.down .chg, .card.down .sym {{}}   /* 灰度屏靠 ▲▼ 与符号区分，不用颜色 */
  .card.err .chg {{ font-weight: 400; font-style: italic; }}
  .spark {{ width: 100%; height: auto; display: block; }}   /* 等比缩放，线宽各向一致 */
  footer {{ margin-top: 12px; font-size: 13px; text-align: center; opacity: .7; }}
</style>
</head>
<body>
<header>
  <h1>行情看板</h1>
  <span class="meta">更新 {updated} · 延迟~15min</span>
</header>
<div class="grid">
{cards}
</div>
<footer>虚线 = 昨收 · 每 5 分钟自动刷新</footer>
</body>
</html>
"""


if __name__ == "__main__":
    build()
