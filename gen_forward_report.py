#!/usr/bin/env python3
"""读 signal_log.json → forward_report.html：从开始追踪起，每次触发买入/强买入信号后的**真实**
5/10/20 日表现汇总。这是无偏的样本外前瞻验证——对照回测(backtest_stats.html)的纸面胜率，看
过拟合到底吃掉多少。数据攒得越多越可信。重跑：python gen_forward_report.py
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
LOG = ROOT / "signal_log.json"


def winrate(recs, key):
    """一组记录在某持有期(fwd5/10/20)的真实胜率 → (胜率%|None, 样本数, 平均收益%|None)。"""
    vals = [r[key] for r in recs if r.get(key) is not None]
    if not vals:
        return None, 0, None
    return round(sum(v > 0 for v in vals) / len(vals) * 100), len(vals), round(sum(vals) / len(vals) * 100, 1)


def cells(recs):
    out = ""
    for key in ("fwd5", "fwd10", "fwd20"):
        wr, n, avg = winrate(recs, key)
        if wr is None:
            out += '<td class="num mut">—</td>'
        else:
            cls = "hi" if wr >= 70 else "mid" if wr >= 50 else "lo"
            out += f'<td class="num {cls}">{wr}% <span class="sub2">({n}·均{avg:+.1f}%)</span></td>'
    return out


def group_rows(log, field, order=None):
    keys = order or sorted({r[field] for r in log})
    rows = ""
    for k in keys:
        recs = [r for r in log if r[field] == k]
        if not recs:
            continue
        done = sum(1 for r in recs if r.get("fwd20") is not None)
        rows += f'<tr><td class="lbl">{k}</td><td class="num">{len(recs)}<span class="sub2">（{done}完成）</span></td>{cells(recs)}</tr>'
    return rows


def pct(v):
    return "进行中" if v is None else f'<span style="color:{"var(--hi)" if v > 0 else "var(--lo)"}">{v * 100:+.1f}%</span>'


def main():
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else []
    total = len(log)
    done = sum(1 for r in log if r.get("fwd20") is not None)
    dates = sorted(r["date"] for r in log)
    span = f"{dates[0]} 起" if dates else "尚未开始"

    overview = (f'<div class="ov"><b>{total}</b> 条记录 · <b>{done}</b> 条已满20日(可算) · '
                f'<b>{total - done}</b> 条进行中 · 追踪 {span} · 今日 {date.today().isoformat()}</div>')

    if not log:
        body = '<div class="empty">signal_log.json 还是空的——等下一次买入/强买入信号触发,这里就会开始记录。</div>'
    else:
        overall = f'<tr><td class="lbl"><b>全部信号</b></td><td class="num">{total}<span class="sub2">（{done}完成）</span></td>{cells(log)}</tr>'
        by_level = group_rows(log, "level", ["强买入", "买入"])
        by_window = group_rows(log, "window", ["5年", "2年", "5年+2年"])
        note = ('<p class="note">胜率后括号 = (样本数·平均收益)。<b>只有到了触发后第 20 个交易日</b>的记录才计入 20 日列'
                '(5/10 日同理)——所以早期"进行中"多、样本少很正常,攒久了才可信。绿≥70% / 琥珀50-70% / 红&lt;50%。</p>')
        summ = ('<h2>真实前瞻胜率</h2>'
                '<div class="tw"><table><thead><tr><th>分组</th><th class="num">记录数</th>'
                '<th class="num">5日</th><th class="num">10日</th><th class="num">20日</th></tr></thead>'
                f'<tbody>{overall}<tr class="gap"><td colspan="5">— 按级别 —</td></tr>{by_level}'
                f'<tr class="gap"><td colspan="5">— 按窗口 —</td></tr>{by_window}</tbody></table></div>' + note)

        det = ""
        for r in sorted(log, key=lambda x: x["date"], reverse=True):
            lvlcls = "strong" if r["level"] == "强买入" else "buy"
            det += (f'<tr><td>{r["date"]}</td><td class="tk">{r["ticker"]}</td><td class="nm">{r["name"]}</td>'
                    f'<td class="sig {lvlcls}">{r["level"]}·{r["signal"]}</td><td class="win">{r["window"]}</td>'
                    f'<td class="num">{r["entry_close"]}</td>'
                    f'<td class="num">{pct(r.get("fwd5"))}</td><td class="num">{pct(r.get("fwd10"))}</td><td class="num">{pct(r.get("fwd20"))}</td></tr>')
        detail = ('<h2>完整记录（最新在上）</h2>'
                  '<div class="tw"><table><thead><tr><th>触发日</th><th>代码</th><th>名称</th><th>信号</th>'
                  '<th>窗口</th><th class="num">触发收盘</th><th class="num">5日</th><th class="num">10日</th><th class="num">20日</th></tr></thead>'
                  f'<tbody>{det}</tbody></table></div>')
        body = summ + detail

    html = TEMPLATE.replace("{{OVERVIEW}}", overview).replace("{{BODY}}", body)
    (ROOT / "forward_report.html").write_text(html, encoding="utf-8")
    print(f"✅ forward_report.html 生成（共 {total} 条记录，{done} 条已满20日）")


TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>前瞻战绩 · 真实信号表现追踪</title>
<style>
  :root{--bg:#eef1f4;--card:#fff;--ink:#1a1d21;--muted:#8a9099;--line:#e4e8ec;--head:#f5f6f8;
    --hi:#12924f;--mid:#b7791f;--lo:#d92d20;--strong:#0b7a41;--buy:#12924f;}
  @media(prefers-color-scheme:dark){:root{--bg:#0d1015;--card:#161a20;--ink:#e6e9ee;--muted:#8b93a0;--line:#252b33;
    --head:#1c2129;--hi:#43d18f;--mid:#e0a53f;--lo:#ff6b60;--strong:#43d18f;--buy:#43d18f;}}
  :root[data-theme="light"]{--bg:#eef1f4;--card:#fff;--ink:#1a1d21;--muted:#8a9099;--line:#e4e8ec;--head:#f5f6f8;--hi:#12924f;--mid:#b7791f;--lo:#d92d20;--strong:#0b7a41;--buy:#12924f;}
  :root[data-theme="dark"]{--bg:#0d1015;--card:#161a20;--ink:#e6e9ee;--muted:#8b93a0;--line:#252b33;--head:#1c2129;--hi:#43d18f;--mid:#e0a53f;--lo:#ff6b60;--strong:#43d18f;--buy:#43d18f;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);line-height:1.5;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
  .wrap{max-width:920px;margin:0 auto;padding:40px 18px 72px}
  .eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:700;margin:0 0 8px}
  h1{font-size:24px;font-weight:750;margin:0 0 10px}
  h2{font-size:17px;font-weight:700;margin:30px 0 10px}
  .lede{font-size:14px;color:var(--muted);max-width:78ch;margin:0 0 14px;line-height:1.65}
  .lede b{color:var(--ink)}
  .ov{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 15px;font-size:13.5px;color:var(--muted);margin-bottom:6px}
  .ov b{color:var(--ink);font-variant-numeric:tabular-nums}
  .empty{background:var(--card);border:1px dashed var(--line);border-radius:12px;padding:28px;text-align:center;color:var(--muted);margin-top:20px}
  .tw{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow-x:auto}
  table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
  th,td{padding:9px 12px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
  th{background:var(--head);font-size:12px;color:var(--muted);font-weight:600}
  th.num,td.num{text-align:right}
  tbody tr:last-child td{border-bottom:none}
  .lbl{font-weight:600}
  td.tk{font-weight:700}.td.nm,td.nm{color:var(--muted);font-size:12.5px}
  .sig.strong{color:var(--strong);font-weight:600}.sig.buy{color:var(--buy)}
  .win{font-size:12px;color:var(--muted)}
  .num.hi{color:var(--hi);font-weight:600}.num.mid{color:var(--mid);font-weight:600}.num.lo{color:var(--lo);font-weight:600}
  .sub2{font-size:10.5px;color:var(--muted);font-weight:400}
  tr.gap td{background:var(--head);color:var(--muted);font-size:11.5px;text-align:center;padding:4px}
  .mut{color:var(--muted)}
  .note{font-size:12px;color:var(--muted);line-height:1.7;margin-top:12px}
  .note b{color:var(--ink)}
  a{color:#2563eb}
</style></head><body>
<div class="wrap">
  <p class="eyebrow">前瞻战绩 · Forward Tracking</p>
  <h1>真实信号表现追踪</h1>
  <p class="lede">从开始追踪起,每次触发买入/强买入信号后,系统逐日记录该标的**真实**的 5/10/20 日走势。这是<b>无偏的样本外验证</b>——回测(<a href="backtest_stats.html">backtest_stats.html</a>)的胜率是"同数据选参数又评估",有过拟合乐观偏差;这里是真金白银的未来。<b>攒得越多越可信</b>,拿两边一比就知道纸面 vs 实盘差多少。</p>
  {{OVERVIEW}}
  {{BODY}}
</div></body></html>"""


if __name__ == "__main__":
    main()
