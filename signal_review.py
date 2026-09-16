#!/usr/bin/env python3
"""信号条件复核（滚动失效机制）——把**真实前瞻结果**并入回测样本，重算胜率，不达当初校准门槛的档自动停用。

动机：signal_config.json 的阈值是"同数据选参数又评估"，有过拟合乐观偏差(gen_signal_config 自己也这么写)。
系统跑起来后 signal_log.json 在攒无偏的样本外数据——把两者合并重算，就能让门槛随真实战绩自我修正：
纸面 100% 的档如果实盘一路输，会自己退场，不用人肉盯。

⚠️ 口径一致性(本模块第一原则)：胜率一律**按触发条数**算，与 gen_signal_config.rates() 和
daily_alert.pstat() 完全同源——"当初怎么进来的，就怎么考核"。独立事件数**不参与任何概率计算**，
只做一件事：决定"前瞻样本够不够格开始判"(闸门①)，这与原系统把独立事件数当展示项的定位一致。

⚠️ 淘汰标准 ≠ 准入标准(第二原则)：qualifies() 的 95%/80% 是"从候选里挑最好"的**选拔线**，
拿它当**淘汰线**，等于要求信号在样本外持续维持样本内的过拟合水平。150 槽位蒙特卡洛实测：
那样做的误杀率(真实胜率仍有 80% 却被停用)高达 33%——三个好信号杀掉一个。故改为三态：

  active ──跌破 FLOOR 且置信确认──→ disabled(停用，不再推送)
     ↑ ↓ (强买入档不再拔尖 / 回升到 95%)
  demoted(降级：原强买入档改按买入级别继续推送，不消失)

实测误杀率降到 18.5%，击杀率(真实胜率已跌到 45% 时正确停用)58.9%。买入档只有 active/disabled。

三道闸门(缺一不可，防止拿噪声杀好信号)：
  ① 样本充足性闸门：前瞻记录按 event_dedup(GAP=20 交易日)数出独立事件数，< MIN_FWD_EVENTS 一律不动。
     ——TSLA 破150日布林 2026-07-23~08-07 连续 12 天触发、前瞻窗口高度重叠，实为 1 个事件。
       若不设闸门，一波行情就能解锁停用权限，反向时同样会用 1 波噪声杀掉一个好档。
  ② 跌破地板：合并后(历史 + 前瞻，均按条数)的 5/10/20 日胜率，最弱项须真的 ≤ FLOOR(接近抛硬币)。
  ③ 置信下界：对合并样本(同样按条数)算 Wilson 单侧 90% 下界，须确信低于 FLOOR 才动手。
     ——避免 n 小时一两个坏样本就把档打掉。

可逆：停用不是删除。停用/降级档仍逐日影子记录(shadow)继续攒前瞻数据，统计回升会自动恢复。
不改 signal_config.json（那是 gen_signal_config 的产物，重跑会覆盖），只写 signal_overrides.json 叠加在上层。

产物 signal_overrides.json:
  {"reviewed": "YYYY-MM-DD",
   "slots": {"TSLA": {"2y:boll_s": {"disabled": true, "since": "...", "reason": "...", "rates": [...]}}},
   "history": [{"date","ticker","slot","action","reason"}, ...]}

独立重跑(不依赖 daily_alert)：
  python signal_review.py             # 体检：每个组合攒了多少前瞻数据、够不够格判定
  python signal_review.py --backfill  # 给老记录固化 slots 字段(改阈值前务必跑一次，防战绩丢失)
"""
import json
import math
import os
import re
from datetime import date

from event_dedup import event_reps

ROOT = os.path.dirname(os.path.abspath(__file__))
OVERRIDE_PATH = os.path.join(ROOT, "signal_overrides.json")

# 判定门槛：与 gen_signal_config.py 保持一致（当初怎么进来的，就怎么考核）
FLOOR, STRONG_HI, BUY_HI = 55, 95, 80
# 统计闸门
MIN_FWD_EVENTS = 3      # 前瞻独立事件数下限：不够就不判（数据不足时系统保持原样，绝不乱动）
# 实测(150 槽位蒙特卡洛)：3 与 5 的误杀率几乎相同(18.5% vs 19.7%)——因为每个独立事件平均带进
# 2.9 条记录，K=3 已有约 9 条样本。K=5 击杀率更高(58.9%→71.8%)，但要多等数月才够格判定。
# 取 3：让机制早些生效，代价仅约 1pp 误杀。真正压误杀的是下面的"降级而非停用"，不是这个闸门。
Z = 1.2816              # Wilson 单侧 90% 置信下界
HORIZONS = (5, 10, 20)


# ---------- 基础统计 ----------

def wilson_lb(wins: int, n: int, z: float = Z) -> float:
    """胜率的 Wilson 单侧下界(%)。n 小时显著低于点估计 → 天然要求"证据"而非"巧合"。"""
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom) * 100


def qualifies(rates, hi: float) -> bool:
    """gen_signal_config 的原口径：≥2 个窗口 > hi，且三个都 > FLOOR。"""
    rs = [r for r in rates if r is not None]
    return len(rs) == 3 and sum(r > hi for r in rs) >= 2 and min(rs) > FLOOR


def tier_hi(kind: str) -> float:
    """档位 → 对应门槛。*_s = 强买入(95%)，*_b = 买入(80%)。"""
    return STRONG_HI if kind.endswith("_s") else BUY_HI


# ---------- 日志 → 槽位映射 ----------

SLOT_RE = re.compile(r"^(5y|2y):(rsi|boll)_([sb])$")
_RSI_RE = re.compile(r"RSI\(14\)<(\d+)")
_BOLL_RE = re.compile(r"破(\d+)日布林")
_WIN_MAP = {"5年": ("5y",), "2年": ("2y",), "5年+2年": ("5y", "2y")}


def record_slots(rec: dict, cfg: dict) -> list:
    """一条 signal_log 记录 → 它对应的槽位列表 ["2y:rsi_b", ...]。

    新记录直接带 slots 字段(daily_alert 写入，5年+2年共振时含两个槽)；
    老记录从 signal 文案反解阈值再与该标的 config 比对。"""
    if rec.get("slots"):
        return [s for s in rec["slots"] if SLOT_RE.match(s)]
    if rec.get("slot") and SLOT_RE.match(rec["slot"]):
        return [rec["slot"]]
    c = cfg.get(rec["ticker"])
    if not c:
        return []
    sig = rec.get("signal", "")
    m = _RSI_RE.search(sig)
    fam, val = ("rsi", int(m.group(1))) if m else (None, None)
    if fam is None:
        m = _BOLL_RE.search(sig)
        if not m:
            return []
        fam, val = "boll", int(m.group(1))
    # 强/买入两档周期或阈值相同时(gen_signal_config 允许 bs == bb)，单靠数值无法区分 → 用记录的 level 消歧
    tiers = ("s",) if rec.get("level") == "强买入" else ("b",) if rec.get("level") == "买入" else ("s", "b")
    out = []
    for w in _WIN_MAP.get(rec.get("window", ""), ()):
        for tier in tiers:
            if (c.get(w) or {}).get(fam, {}).get(tier) == val:
                out.append(f"{w}:{fam}_{tier}")
    return out


def forward_stats(recs: list, dates_index: dict) -> dict:
    """一组前瞻记录 → 统计。
    dates_index: {ticker: {date_str: 交易日序号}}，用于按交易日间隔做事件去重(与回测同一把尺)。

    返回 {"n":全触发数, "ev":独立事件数, "rates":[r5,r10,r20], "wins":[..], "ns":[..]}。
    胜率一律按条数(与回测/校准同口径)；ev 只用于样本充足性闸门，不参与概率计算。"""
    out = {"n": len(recs), "ev": 0, "rates": [None] * 3, "wins": [0] * 3, "ns": [0] * 3}
    if not recs:
        return out
    idx = dates_index.get(recs[0]["ticker"], {})
    pos, worst = [], []
    for i, r in enumerate(recs):
        p = idx.get(r["date"])
        pos.append(p if p is not None else i)          # 拿不到交易日序号就退化为出现顺序(仍能合并连击)
        worst.append(r.get("fwd20") if r.get("fwd20") is not None else 0.0)
    out["ev"] = len(event_reps(pos, worst))            # 仅计数：相邻 ≤GAP 交易日的连击合并为一波
    for j, h in enumerate(HORIZONS):
        vals = [r[f"fwd{h}"] for r in recs if r.get(f"fwd{h}") is not None]
        if vals:
            out["ns"][j] = len(vals)
            out["wins"][j] = sum(1 for v in vals if v > 0)
            out["rates"][j] = round(out["wins"][j] / len(vals) * 100)
    return out


# ---------- 复核主逻辑 ----------

def merge_rates(hist, fwd):
    """历史 + 前瞻 → (合并胜率, 合并胜数, 合并样本数)——**全触发口径**。

    hist = pstat 产出 [n, r5, r10, r20, ev, w5, w10, w20]（后 3 项可缺，缺则由 rate 反推）。
    口径必须与 gen_signal_config.rates() / daily_alert.pstat() 完全一致(都按条数)，
    否则"当初怎么进来的"和"现在怎么考核"用的不是同一把尺，判定失去意义。
    独立事件数只作样本充足性闸门(见 review_slots)，不参与任何概率计算。"""
    if not hist or hist[0] == 0:
        return fwd["rates"], fwd["wins"], fwd["ns"]
    hn = hist[0]
    hw = hist[5:8] if len(hist) >= 8 else [round((hist[1 + j] or 0) / 100 * hn) for j in range(3)]
    wins = [hw[j] + fwd["wins"][j] for j in range(3)]
    ns = [hn + fwd["ns"][j] for j in range(3)]
    return [round(wins[j] / ns[j] * 100) if ns[j] else None for j in range(3)], wins, ns


def review_slots(hist_stats: dict, log: list, cfg: dict, dates_index: dict, today: str = None):
    """核心：对每个已配置槽位做复核 → (slots_state, changes)。

    hist_stats: {tk: {"5y": {kind: pstat列表}, "2y": {...}}}   ← daily_alert 主循环里已算好，零额外开销
    log:        signal_log.json 全量（含 shadow 记录）
    cfg:        signal_config.json
    """
    today = today or date.today().isoformat()
    prev = load_overrides()
    prev_slots = prev.get("slots", {})
    slots_state, changes = {}, []

    # 前瞻记录按 (ticker, slot) 归组
    by_slot = {}
    for r in log:
        for s in record_slots(r, cfg):
            by_slot.setdefault((r["ticker"], s), []).append(r)

    for tk, wins_cfg in cfg.items():
        for w in ("5y", "2y"):
            wc = wins_cfg.get(w) or {}
            for fam in ("rsi", "boll"):
                for tier in ("s", "b"):
                    if not (wc.get(fam) or {}).get(tier):
                        continue                       # 该档本来就没配置
                    kind, slot = f"{fam}_{tier}", f"{w}:{fam}_{tier}"
                    hist = ((hist_stats.get(tk) or {}).get(w) or {}).get(kind)
                    recs = sorted(by_slot.get((tk, slot), []), key=lambda x: x["date"])
                    fwd = forward_stats(recs, dates_index)
                    rates, wins, ns = merge_rates(hist, fwd)      # 全触发口径，与校准一致
                    st0 = prev_slots.get(tk, {}).get(slot) or {}
                    was_disabled, was_demoted = bool(st0.get("disabled")), bool(st0.get("demoted"))

                    # 置信下界：同样按条数算(与胜率同源)，取三个窗口里最弱的那条腿
                    weakest = min(wilson_lb(wins[j], ns[j]) for j in range(3))
                    # 闸门只管"够不够格开始判"，不参与概率计算：连续破位的重叠触发不算新证据
                    enough = fwd["ev"] >= MIN_FWD_EVENTS
                    valid = [r for r in rates if r is not None]

                    # 淘汰标准 ≠ 准入标准。qualifies() 的 95%/80% 是从候选里"挑最好"的选拔线，
                    # 拿它当淘汰线等于要求信号在样本外持续维持样本内的过拟合水平 → 实测误杀 33%。
                    # 改为：真的跌到 FLOOR(接近抛硬币)才停用；强买入只是不再拔尖 → 降级为买入，不消失。
                    bad = bool(valid) and min(valid) <= FLOOR and weakest < FLOOR
                    keeps_strong = qualifies(rates, STRONG_HI)
                    cur = ("disabled" if was_disabled else "demoted" if was_demoted else "active")
                    if cur == "active" and not enough:
                        tgt = "active"                       # 样本不够，一律不动
                    elif bad:
                        tgt = "disabled"
                    elif tier == "s" and not keeps_strong:
                        tgt = "demoted"                      # 仅强买入档有降级态；买入档只有 active/disabled
                    else:
                        tgt = "active"

                    state = {"rates": rates, "fwd_n": fwd["n"], "fwd_ev": fwd["ev"],
                             "hist_n": (hist or [0])[0], "wilson_lb": round(weakest, 1)}
                    if tgt == "disabled":
                        state["disabled"] = True
                        state["reason"] = (f"合并 5/10/20 日胜率 {rates} 最弱项已跌破 {FLOOR}%，"
                                           f"Wilson 90% 下界 {weakest:.1f}%；前瞻 {fwd['n']} 次触发/"
                                           f"{fwd['ev']} 个独立事件")
                    elif tgt == "demoted":
                        state["demoted"] = True
                        state["reason"] = (f"合并胜率 {rates} 已不满足强买入(需≥2项>{STRONG_HI}%)，"
                                           f"但最弱项仍 >{FLOOR}% → 降级为买入继续使用")
                    if tgt != "active":
                        state["since"] = ((prev_slots.get(tk, {}).get(slot) or {}).get("since")
                                          if cur == tgt else today) or today
                        slots_state.setdefault(tk, {})[slot] = state
                    if tgt != cur:
                        changes.append((tk, slot, {"disabled": "disable", "demoted": "demote",
                                                   "active": "enable"}[tgt],
                                        state.get("reason", f"合并胜率回升达标 {rates}")))

    return slots_state, changes


# ---------- 持久化 ----------

def load_overrides() -> dict:
    try:
        with open(OVERRIDE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def slot_states(ov: dict, tk: str, window: str):
    """daily_alert 用：该标的该窗口(5y/2y)的 (已停用档集合, 已降级档集合)，元素形如 "rsi_b"。
    停用 = 不再推送(仍影子记账)；降级 = 强买入档改按买入级别推送。"""
    off, dem = set(), set()
    for slot, st in (ov.get("slots", {}).get(tk) or {}).items():
        m = SLOT_RE.match(slot)
        if not m or m.group(1) != window:
            continue
        kind = f"{m.group(2)}_{m.group(3)}"
        if st.get("disabled"):
            off.add(kind)
        elif st.get("demoted"):
            dem.add(kind)
    return off, dem


def save_overrides(slots_state: dict, changes: list, today: str = None):
    today = today or date.today().isoformat()
    prev = load_overrides()
    hist = prev.get("history", [])
    for tk, slot, action, reason in changes:
        hist.append({"date": today, "ticker": tk, "slot": slot, "action": action, "reason": reason})
    payload = {"reviewed": today, "slots": slots_state, "history": hist[-500:]}
    with open(OVERRIDE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return payload


def needs_review(today: str = None) -> bool:
    """当天是否还没复核过（配合每日第一次扫描；FORCE_REVIEW=true 可强制）。"""
    if os.environ.get("FORCE_REVIEW") == "true":
        return True
    return load_overrides().get("reviewed") != (today or date.today().isoformat())


_ICON = {"disable": "🚫 停用", "demote": "⬇️ 降级为买入", "enable": "♻️ 恢复"}


def describe(changes: list) -> str:
    if not changes:
        return "信号条件复核：无变更"
    lines = ["信号条件复核：%d 项变更" % len(changes)]
    for tk, slot, action, reason in changes:
        lines.append(f"  {_ICON.get(action, action)} {tk} {slot} — {reason}")
    return "\n".join(lines)


# ---------- 独立运行(诊断用) ----------

def main():
    import argparse
    ap = argparse.ArgumentParser(description="信号条件复核（默认只报告不写文件）")
    ap.add_argument("--write", action="store_true", help="把结果写入 signal_overrides.json")
    ap.add_argument("--backfill", action="store_true",
                    help="给老记录补写 slots 字段(按当前 config 反解一次并固化)")
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "signal_config.json"), encoding="utf-8"))
    log_path = os.path.join(ROOT, "signal_log.json")
    log = json.load(open(log_path, encoding="utf-8"))

    if args.backfill:
        # 为什么必须回填：老记录靠 signal 文案反解阈值来定位槽位。一旦重跑 gen_signal_config
        # 改了阈值(如 rsi.b 从 30 调到 28)，老记录就再也匹配不上任何槽 → 历史战绩静默丢失。
        # 趁映射还正确，把结果固化成 slots 字段。只补不覆盖，可重复执行。
        n = 0
        for r in log:
            if not r.get("slots"):
                s = record_slots(r, cfg)
                if s:
                    r["slots"] = s
                    n += 1
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=1)
        miss = [f"{r['ticker']}/{r['date']}/{r.get('signal')}" for r in log if not r.get("slots")]
        print(f"✅ 已回填 {n} 条记录的 slots 字段"
              + (f"；{len(miss)} 条无法映射(config 已变?): {miss[:5]}" if miss else "；全部映射成功"))
        return

    # 独立运行时没有主循环算好的历史统计 → 只看前瞻侧，给出"数据攒够了没"的体检
    by_slot = {}
    for r in log:
        for s in record_slots(r, cfg):
            by_slot.setdefault((r["ticker"], s), []).append(r)

    print(f"signal_log: {len(log)} 条记录 · {len(by_slot)} 个 (标的,槽位) 组合")
    print(f"判定闸门：前瞻独立事件 ≥ {MIN_FWD_EVENTS} 才允许判定\n")
    print(f"{'标的':<7}{'槽位':<12}{'触发':>4}{'独立事件':>8}{'完成20日':>9}  前瞻胜率 5/10/20     可判定")
    ready = 0
    for (tk, slot), recs in sorted(by_slot.items()):
        f = forward_stats(sorted(recs, key=lambda x: x["date"]), {})
        done = sum(1 for r in recs if r.get("fwd20") is not None)
        rs = "/".join("—" if r is None else f"{r}%" for r in f["rates"])
        can = f["ev"] >= MIN_FWD_EVENTS
        ready += can
        print(f"{tk:<7}{slot:<12}{f['n']:>4}{f['ev']:>8}{done:>9}  {rs:<18}  {'✅' if can else '❌ 样本不足'}")
    print(f"\n{ready}/{len(by_slot)} 个组合的前瞻样本已足够做停用判定。")
    if args.write:
        print("\n⚠️ 独立运行缺少历史回测统计，--write 只能写空状态；"
              "正式复核请走 daily_alert.py（它在主循环里已算好历史侧）。")


if __name__ == "__main__":
    main()
