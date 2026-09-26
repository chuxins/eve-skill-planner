"""技能规划：需求技能闭包 + 训练时间估算（全离线，SDE + ESI 技能/属性）。

- 需求技能：舰船/装备的 requiredSkill1..5（attr 182-186）配 requiredSkill*Level
  （277/278/279/1286/1287），递归展开前置技能（技能自身也带 requiredSkill*），
  同一技能取「所需最高等级」。
- 训练时间：SP(level) = 250 × rank × 2^(2.5·level − 2.5)（rank = attr 275
  skillTimeConstant），训练速率 = 主属性 + 副属性/2（SP/分钟，属性取 ESI 有效值）。
- 输出按「前置优先」拓扑排序，保证列出的计划可以自上而下依次训练。
"""

# 需求技能 / 等级 / 学习属性 / 技能倍率（SDE attributeID）
A_REQ_SKILL = (182, 183, 184, 185, 186)
A_REQ_LEVEL = (277, 278, 279, 1286, 1287)
A_PRIMARY, A_SECONDARY, A_RANK = 180, 181, 275

# SDE primaryAttribute/secondaryAttribute 的取值 = 属性 ID → ESI attributes 键
ATTR_KEYS = {
    164: "charisma",
    165: "intelligence",
    166: "memory",
    167: "perception",
    168: "willpower",
}
# 属性 ID → 中文名（训练时间明细展示用）
ATTR_NAMES = {
    "charisma": "魅力", "intelligence": "智力", "memory": "记忆",
    "perception": "感知", "willpower": "毅力",
}
DEFAULT_ATTRS = {"charisma": 17, "intelligence": 17, "memory": 17,
                 "perception": 17, "willpower": 17}


def sp_to_level(rank, level):
    """从 0 级练到 level 级累计所需技能点（与游戏/ pyfa 口径一致）。"""
    level = int(level or 0)
    if level <= 0:
        return 0.0
    return 250.0 * float(rank or 1.0) * 2.0 ** (2.5 * level - 2.5)


def _direct_requirements(sde, tid):
    """某类型「直接」需求的 (技能 tid, 等级) 列表。"""
    ta = sde.type_attrs.get(tid, {})
    out = []
    for aid, lid in zip(A_REQ_SKILL, A_REQ_LEVEL):
        sk = ta.get(aid)
        if not sk:
            continue
        out.append((int(sk), int(ta.get(lid) or 1)))
    return out


def collect_requirements(sde, tids):
    """{技能 tid: 所需等级}，递归含前置技能（同技能取最高等级）。"""
    req = {}
    stack = [int(t) for t in tids if t]
    seen = set()
    while stack:
        tid = stack.pop()
        if tid in seen:
            continue
        seen.add(tid)
        for sk, lv in _direct_requirements(sde, tid):
            if lv > req.get(sk, 0):
                req[sk] = lv
            stack.append(sk)
    return req


def skill_time(sde, skill_tid, from_level, to_level, attrs):
    """某技能 from_level → to_level 的训练秒数（attrs 为 ESI 有效属性值）。

    attrs 形如 {"perception": 24, "willpower": 24, ...}；缺项回退基础 17。
    """
    from_level, to_level = int(from_level or 0), int(to_level or 0)
    if to_level <= from_level:
        return 0.0
    ta = sde.type_attrs.get(skill_tid, {})
    rank = ta.get(A_RANK, 1.0) or 1.0
    p_key = ATTR_KEYS.get(int(ta.get(A_PRIMARY) or 167), "perception")
    s_key = ATTR_KEYS.get(int(ta.get(A_SECONDARY) or 168), "willpower")
    eff = dict(DEFAULT_ATTRS)
    eff.update({k: v for k, v in (attrs or {}).items() if v})
    rate = eff[p_key] + eff[s_key] / 2.0          # SP / 分钟
    if rate <= 0:
        return None
    sp = sp_to_level(rank, to_level) - sp_to_level(rank, from_level)
    return sp / rate * 60.0


def _topo_order(sde, skills):
    """前置优先排序（Kahn）：前置技能先于依赖它的技能；同批按技能名排序。"""
    deps = {sk: [p for p, _ in _direct_requirements(sde, sk) if p in skills]
            for sk in skills}
    order, done, remaining = [], set(), set(skills)
    while remaining:
        ready = sorted(sk for sk in remaining
                       if all(d in done for d in deps[sk]))
        if not ready:                    # 数据成环（异常）→ 兜底按 id 排序，避免死循环
            ready = sorted(remaining)
        for sk in ready:
            order.append(sk)
            done.add(sk)
            remaining.discard(sk)
    return order


def _skill_row(sde, skill_tid, need, current, attrs):
    row = {"tid": skill_tid, "name": sde.name(skill_tid), "required": need,
           "current": current, "ok": current >= need}
    if row["ok"]:
        return row
    ta = sde.type_attrs.get(skill_tid, {})
    rank = ta.get(A_RANK, 1.0) or 1.0
    secs = skill_time(sde, skill_tid, current, need, attrs)
    p_key = ATTR_KEYS.get(int(ta.get(A_PRIMARY) or 167), "perception")
    s_key = ATTR_KEYS.get(int(ta.get(A_SECONDARY) or 168), "willpower")
    row.update({
        "seconds": round(secs, 1) if secs is not None else None,
        "sp": round(sp_to_level(rank, need) - sp_to_level(rank, current), 1),
        "rank": round(rank, 2),
        "primary": p_key, "secondary": s_key,
        "primary_name": ATTR_NAMES.get(p_key, p_key),
        "secondary_name": ATTR_NAMES.get(s_key, s_key),
    })
    return row


def build_plan(sde, ship_tid, item_tids, skills, attrs):
    """技能计划：需求技能 + 当前等级 + 缺口 + 训练时间（前置优先排序）。

    skills: {技能 tid: 当前等级}（ESI read_skills）
    attrs : {"perception": 24, ...} 有效属性（ESI attributes 的 base+implant）
    """
    skills = {int(k): int(v) for k, v in (skills or {}).items()}
    reqs = collect_requirements(sde, [int(ship_tid)] + list(item_tids or []))
    rows = [_skill_row(sde, sk, reqs[sk], skills.get(sk, 0), attrs)
            for sk in _topo_order(sde, reqs)]
    missing = [r for r in rows if not r["ok"]]
    return {
        "ship": {"tid": int(ship_tid), "name": sde.name(int(ship_tid))},
        "attributes": dict(DEFAULT_ATTRS, **(attrs or {})),
        "requirements": rows,
        "missing": missing,
        "total_seconds": round(sum(r["seconds"] or 0 for r in missing), 1),
    }
