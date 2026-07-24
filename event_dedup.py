#!/usr/bin/env python3
"""独立事件去重(event de-duplication)——修正重叠样本对回溯胜率的虚增。

问题:同一波下跌里连续多日破位会连续触发同一个信号(如 TSLA 2026-04-06~04-13 每天都破 150 日布林),
它们的 5/10/20 日前瞻窗口高度重叠——本质是"同一段未来行情被数了好几遍",有效样本量远小于名义次数。
把重叠触发当独立证据,会让胜率的置信度虚高、污染"N 小=极端=大机会"的判据。

去重规则(链式聚类):按时间排序,相邻触发的**交易日位置差 ≤ GAP** 归为同一事件(默认 20 个交易日
= 一个持有期,刚好让 20 日前瞻窗口不重叠);每个事件取**簇内 RSI 最低那天**(跌得最狠、最极端)为代表。
胜率、触发数一律以独立事件(代表点)计,原始触发数仅作参考展示。

被 gen_signal_config / build_ticker_stats / gen_backtest_table / daily_alert 共用,保证四处口径一致。
index.html(工具端)另有一份等价的 JS 实现(eventReps),两边必须同步。
"""

GAP = 20   # 交易日；相邻触发间隔 ≤ GAP 视为同一下跌事件


def event_reps(positions, rsis, gap=GAP):
    """positions: 各触发点在该标的完整交易日序列里的位置(int，未必已排序)；rsis: 对应 RSI。
    返回代表点在输入序列中的下标 list(每个独立事件一个，取簇内 RSI 最低那天)。"""
    n = len(positions)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: positions[i])
    reps, cluster, last = [], [], None
    for i in order:
        if last is not None and positions[i] - last > gap:
            reps.append(min(cluster, key=lambda j: rsis[j]))
            cluster = []
        cluster.append(i)
        last = positions[i]
    reps.append(min(cluster, key=lambda j: rsis[j]))
    return reps


def dedup(sub, pos_col="_pos", rsi_col="rsi14"):
    """sub = 触发子集 DataFrame(须含 pos_col 时间位置列 + rsi_col)。
    返回 (代表行 DataFrame, 原始触发数, 独立事件数)。"""
    if len(sub) == 0:
        return sub, 0, 0
    reps = event_reps(list(sub[pos_col]), list(sub[rsi_col]))
    return sub.iloc[reps], len(sub), len(reps)


def cluster_labels(positions, rsis, gap=GAP):
    """给每个触发点标注所属独立事件。返回与输入等长的 (簇号 list[从1递增], 是否为该簇代表 list[bool])。
    代表点 = 簇内 RSI 最低那天。用于明细表按事件分组展示。"""
    n = len(positions)
    if n == 0:
        return [], []
    order = sorted(range(n), key=lambda i: positions[i])
    lab = [0] * n
    reps, cur, cid, last = set(), [], 0, None

    def flush(members, this_cid):
        rep = min(members, key=lambda j: rsis[j])
        for j in members:
            lab[j] = this_cid
        reps.add(rep)

    for i in order:
        if last is not None and positions[i] - last > gap:
            flush(cur, cid)
            cur = []
        if not cur:
            cid += 1
        cur.append(i)
        last = positions[i]
    flush(cur, cid)
    return lab, [j in reps for j in range(n)]
