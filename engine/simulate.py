"""舰船装配模拟引擎（全离线，SDE 驱动）。

目标：与 pyfa/游戏面板一致的属性面板数据。

关键机制（经 pyfa/游戏实测锚定）：
- 技能加成两段式：
  ① 技能自身效果（domain=itemID, modifying=280 等级）把「每级基数」折算出
     加成属性生效值 = 基数 × 等级（如能量栅格管理 attr313 = +5/级 → L5 = 25%）。
  ② 船体作用效果（domain=shipID，func=ItemModifier / LocationRequiredSkill
     Modifier / LocationGroupModifier）以该生效值为修改源按操作符应用。
- 修改顺序：加性（op0）先行 → 乘性（op2/4/6/7）后行；乘性带叠加惩罚
  （豁免：技能加成、损伤控制 groupID=60、回充类 modified=55）。
- 技能必须先于装备加成应用：装备效果以「技能增强后」的模块属性为修改源。
- 结构抗性用 109-113（损控等模块改的就是它，不是 974-977）。
"""

import math

from .data import A_CHARGE_GROUPS, StaticData

CAT_SHIP, CAT_MODULE, CAT_CHARGE, CAT_DRONE, CAT_IMPLANT, CAT_FIGHTER, CAT_SKILL = (
    6, 7, 8, 18, 20, 87, 16)

# 关键属性 ID
A_PG, A_PG_USE = 11, 30
A_CPU, A_CPU_USE = 48, 50
A_CAP, A_RECHARGE = 482, 55
A_HULL_HP, A_ARMOR_HP, A_SHIELD_HP = 9, 265, 263
A_SIGNATURE, A_SCAN_RES, A_MAX_LOCKED, A_MAX_RANGE = 552, 564, 192, 76
A_AGILITY, A_SPEED = 70, 37
A_CARGO, A_DRONE_BAY, A_DRONE_BW, A_MAX_DRONES = 38, 283, 1271, 352
A_WARP, A_WARP_MULT = 1281, 600
A_TURRET_HP, A_LAUNCHER_HP = 102, 101
A_DMG_MULT, A_ROF, A_DURATION, A_NEED = 64, 51, 73, 6
A_EM, A_EXPL, A_KIN, A_THERM = 114, 116, 117, 118
A_ARMOR_REPAIR, A_SHIELD_BOOST = 84, 68
A_SKILL_LEVEL = 280
A_REQ_SKILL = (182, 183, 184, 185, 186)
A_REQ_LEVEL = (277, 278, 279, 1286, 1287)
A_CALIBRATION = 1132
A_OPTIMAL = 54
A_FALLOFF = 158
A_SIG_RES = 620
A_CHARGE_SIZE = 128
A_SHIELD_RECHARGE = 144

# 抗性（共振/抗性系数，0.67 = 33% 基础抗性）
STRUCT_RES = (113, 111, 109, 110)     # em / expl / kin / therm
ARMOR_RES = (267, 268, 269, 270)
SHIELD_RES = (271, 272, 273, 274)
RES_NAMES = ("em", "expl", "kin", "therm")

GROUP_DC = 60                            # 损伤控制分组（免叠加惩罚）
MUL_OPS = (2, 4, 6, 7)

# 推进器 moduleBonus 效果 ID（游戏内特殊处理：全程被动生效）
EFF_MWD = 6730
EFF_AB = 6731

STACK_CONST = 2.22292081
ALIGN_FACTOR = math.log(4.0) / 1e6       # 对齐时间 = 质量×惯性×ln4/1e6


def _stack_penalty(n):
    """第 n 个乘性修正有效系数：1 / 0.869 / 0.571 / 0.283 / ..."""
    if n <= 1:
        return 1.0
    return 0.5 ** ((n - 1) / STACK_CONST) ** 2


def asinh(x):
    return math.log(x + math.sqrt(x * x + 1.0))


class SimulationError(RuntimeError):
    pass


class Modifier:
    """一条 dogma modifier 的展开实例（按数量逐件展开）。"""

    __slots__ = ("domain", "func", "modified", "op", "value",
                 "source", "exempt", "group_id", "skill_id")

    def __init__(self, domain, func, modified, op, value, source, exempt,
                 group_id=None, skill_id=None):
        self.domain = domain
        self.func = func
        self.modified = modified
        self.op = op
        self.value = value
        self.source = source      # "skill" / "module"
        self.exempt = exempt      # 免叠加惩罚
        self.group_id = group_id  # LocationGroupModifier 目标分组
        self.skill_id = skill_id  # LocationRequiredSkillModifier 目标技能


class _Target:
    """(容器, 属性) 上的一批修正，按 加性→乘性 落实。"""

    def __init__(self, container):
        self.container = container
        self.adds = []
        self.sets = []
        self.muls = []            # (delta, pct, exempt)

    def add(self, mod):
        op = mod.op
        if op == 1:                          # 赋值
            self.sets.append(mod.value)
        elif op == 2:                        # 平加（电池 +625 等）
            self.adds.append(mod.value)
        elif op in (0, 4, -1):               # 原始乘法（损控/回充器/技能阶段1）
            delta, pct = mod.value, mod.value - 1.0
            self.muls.append((delta, pct, mod.exempt))
        elif op in (3, 5):                   # 除法（罕见）
            delta = 1.0 / mod.value if mod.value else 1.0
            self.muls.append((delta, delta - 1.0, mod.exempt))
        else:                                # 6 / 7 百分比
            delta = 1.0 + mod.value / 100.0
            pct = mod.value / 100.0
            self.muls.append((delta, pct, mod.exempt))

    def apply(self, current):
        if self.sets:
            current = self.sets[-1]          # 赋值类：最后一次生效
        current += sum(self.adds)            # 加性先行
        if not self.muls:
            return current
        penalized = [m for m in self.muls if not m[2]]
        exempt = [m for m in self.muls if m[2]]
        penalized.sort(key=lambda m: -abs(m[1]))
        factor = 1.0
        for i, (delta, pct, _) in enumerate(penalized):
            factor *= 1.0 + pct * _stack_penalty(i + 1)
        for delta, pct, _ in exempt:
            factor *= delta
        return current * factor


class Fit:
    """一次装配模拟的求解器。"""

    def __init__(self, sde, ship_tid, modules, skills=None, charges=None):
        """
        modules: [(tid, qty)] —— 槽位与机库物品（模块/弹药/无人机/植入体…）。
        skills:  {skill_tid: level}
        charges: {weapon_tid: charge_tid} —— 每门武器显式指定弹药；
                 未指定或与武器装填尺寸不符时回退为按尺寸自动配弹。
        """
        self.sde = sde
        self.ship_tid = ship_tid
        ship = sde.types.get(ship_tid)
        if not ship or ship["category_id"] != CAT_SHIP:
            raise SimulationError(f"无效舰船 typeID: {ship_tid}")
        self.ship = ship
        self.ship_attrs = dict(sde.type_attrs.get(ship_tid, {}))
        self.mod_attrs = {tid: dict(sde.type_attrs.get(tid, {})) for tid, _ in modules}
        self.items = list(modules)
        self.skills = skills or {}
        self.charges = {int(k): int(v) for k, v in (charges or {}).items() if v}
        # 不在装配/货舱里的显式弹药 → 应用加成后的属性（见 _solve_virtual_charges）
        self.charge_attrs = {}

    # ------------------------------------------------------------ 技能
    def _skill_bonus_map(self):
        """两段式①：技能自身效果折算加成属性 = 每级基数 × 等级。"""
        bonus = {}
        for sk_tid, level in self.skills.items():
            if level <= 0:
                continue
            base = self.sde.type_attrs.get(sk_tid, {})
            for eid in self.sde.type_effects.get(sk_tid, {}):
                eff = self.sde.effects.get(eid)
                if not eff:
                    continue
                for m in eff["modifiers"]:
                    if m.get("domain") != "itemID" or m.get("func") != "ItemModifier":
                        continue
                    if m.get("modifyingAttributeID") != A_SKILL_LEVEL:
                        continue
                    tgt = m.get("modifiedAttributeID")
                    if tgt is None or tgt == A_SKILL_LEVEL:
                        continue
                    bonus[(sk_tid, tgt)] = base.get(tgt, 0.0) * level
        return bonus

    def _collect_skill_mods(self, bonus):
        """两段式②：收集技能的 shipID 作用效果（以折算后的生效值为源）。"""
        mods = []
        for sk_tid in self.skills:
            for eid in self.sde.type_effects.get(sk_tid, {}):
                eff = self.sde.effects.get(eid)
                if not eff:
                    continue
                for m in eff["modifiers"]:
                    if m.get("domain") != "shipID":
                        continue
                    tgt = m.get("modifiedAttributeID")
                    value = bonus.get((sk_tid, m.get("modifyingAttributeID")))
                    if tgt is None or value is None:
                        continue
                    op = m.get("operation")
                    if op is None or op not in (0, 1, 2, 3, 4, 5, 6, 7, -1):
                        continue
                    mods.append(Modifier(
                        "shipID", m.get("func", "ItemModifier"), tgt, op, value,
                        source="skill", exempt=True,
                        group_id=m.get("groupID"), skill_id=m.get("skillTypeID")))
        return mods

    def _collect_module_mods(self):
        """装备自身效果（修改源 = 技能增强后的 mod_attrs）。"""
        mods = []
        for tid, qty in self.items:
            gid = self.sde.types.get(tid, {}).get("group_id", 0)
            for eid in self.sde.type_effects.get(tid, {}):
                eff = self.sde.effects.get(eid)
                if not eff:
                    continue
                for m in eff["modifiers"]:
                    domain = m.get("domain")
                    if domain not in ("shipID", "itemID", "otherID", "characterID"):
                        continue
                    tgt = m.get("modifiedAttributeID")
                    mod_aid = m.get("modifyingAttributeID")
                    if tgt is None or mod_aid is None:
                        continue
                    value = self.mod_attrs.get(tid, {}).get(mod_aid)
                    if value is None:
                        continue
                    op = m.get("operation")
                    if op is None or op not in (0, 1, 2, 3, 4, 5, 6, 7, -1):
                        continue
                    # 免叠加惩罚：损伤控制 / 电容回充时间类
                    exempt = gid == GROUP_DC or tgt == A_RECHARGE
                    for _ in range(max(1, int(qty))):
                        mods.append(Modifier(
                            domain, m.get("func", "ItemModifier"), tgt, op, value,
                            source="module", exempt=exempt,
                            group_id=m.get("groupID"), skill_id=m.get("skillTypeID")))
        return mods

    def _requires_skill(self, tid, skill_tid):
        t = self.sde.type_attrs.get(tid, {})
        return any(t.get(aid) == skill_tid for aid in A_REQ_SKILL)

    def _targets_of(self, mod, extra=None):
        """把一条修正展开成 (容器, 目标属性) 列表。

        extra: {tid: 属性字典} —— 一并参与匹配的「虚拟物品」。用于给不在装配里的
        显式弹药算加成（船体/模块的 Location*Modifier 只作用于装配内物品，若不给
        虚拟容器，同款弹药「货舱里」与「下拉框选中」会算出两个伤害）。
        """
        tgt = mod.modified
        if mod.func == "ItemModifier":
            if mod.domain == "shipID":
                return [(self.ship_attrs, tgt)]
            if mod.domain == "itemID":
                return []
        pool = [(self.mod_attrs[tid], tid) for tid in {t for t, _ in self.items}]
        if extra:
            pool += [(attrs, tid) for tid, attrs in extra.items()]
        if mod.func == "LocationRequiredSkillModifier":
            sk = mod.skill_id
            if not sk:
                return []
            return [(attrs, tgt) for attrs, tid in pool if self._requires_skill(tid, sk)]
        elif mod.func == "LocationGroupModifier":
            gid = mod.group_id
            if not gid:
                return []
            return [(attrs, tgt) for attrs, tid in pool
                    if self.sde.types.get(tid, {}).get("group_id") == gid]
        return []

    # ------------------------------------------------------------ 主流程
    def solve(self):
        bonus = self._skill_bonus_map()
        skill_mods = self._collect_skill_mods(bonus)
        self._apply(skill_mods)
        module_mods = self._collect_module_mods()
        self._apply(module_mods)
        self._apply_prop_mods()
        self._solve_virtual_charges(skill_mods + module_mods)
        return self._finalize()

    def _solve_virtual_charges(self, mods):
        """给「不在装配里」的显式弹药算属性：用同一批修正单独过一遍。

        部分模块/船体的修正直接作用在**弹药**伤害属性上（如会战装备对鱼雷），而
        Location*Modifier 只作用于装配内物品；下拉框能选到货舱外的弹药，若不这样
        处理，同款弹药会出现「货舱里能加成、选它反而没加成」的两个伤害。
        """
        if not mods:
            return
        in_fit = {t for t, _ in self.items}
        for tid in set(self.charges.values()):
            if tid in in_fit:
                continue
            attrs = dict(self.sde.type_attrs.get(tid, {}))
            self._apply(mods, extra={tid: attrs})
            self.charge_attrs[tid] = attrs

    def _apply_prop_mods(self):
        """推进器（MWD/AB）特殊处理：moduleBonus 效果按游戏规则被动生效。

        - 速度：× (1 + attr20 速度加成%)
        - 质量：按尺寸加恒定吨位（SDE 未记录模块质量加成，用官方数值表）
          MWD：1MN 250t / 5MN 500t / 50MN 5000t / 500MN 50000t
          AB ：1MN 250t / 10MN 2500t / 100MN 25000t
        - MWD 惩罚：信号半径 ×1.5、惯性调整 ×1.125
        """
        speed_mul, mass_add, sig_mul, agi_mul = 1.0, 0.0, 1.0, 1.0
        for tid, qty in self.items:
            fx = self.sde.type_effects.get(tid, {})
            is_mwd = EFF_MWD in fx
            if not is_mwd and EFF_AB not in fx:
                continue
            a = self.mod_attrs.get(tid, {})
            boost = a.get(20, 0.0)
            speed_mul *= (1.0 + boost / 100.0) ** qty
            mass_add += self._prop_mass(self.sde.name(tid), is_mwd) * qty
            if is_mwd:
                sig_mul *= (1.5 ** qty)
                agi_mul *= (1.125 ** qty)
        if speed_mul != 1.0 or mass_add:
            self.ship_attrs[37] = self.ship_attrs.get(37, 0.0) * speed_mul
            base_mass = self.ship_attrs.get(4) or self.ship.get("mass", 0.0)
            self.ship_attrs[4] = base_mass + mass_add
            self.ship_attrs[552] = self.ship_attrs.get(552, 0.0) * sig_mul
            self.ship_attrs[70] = self.ship_attrs.get(70, 0.0) * agi_mul

    @staticmethod
    def _prop_mass(name, is_mwd):
        import re
        m = re.search(r"(\d+)MN", name or "")
        size = int(m.group(1)) if m else 0
        table_mwd = {1: 250_000, 5: 500_000, 10: 2_500_000,
                     50: 5_000_000, 100: 25_000_000, 500: 50_000_000}
        table_ab = {1: 250_000, 5: 250_000, 10: 2_500_000, 100: 25_000_000}
        return (table_mwd if is_mwd else table_ab).get(size, 0)

    def _apply(self, mods, extra=None):
        """按加性→乘性落实一批修正。

        extra: {tid: 属性字典} —— 虚拟物品容器。提供时**只**作用于这些容器
        （用于给不在装配里的弹药算加成，避免把修正重复施加到装配内物品上）。
        """
        only = {id(attrs) for attrs in extra.values()} if extra else None
        targets = {}
        for mod in mods:
            for container, aid in self._targets_of(mod, extra):
                if only is not None and id(container) not in only:
                    continue
                targets.setdefault((id(container), aid), _Target(container)).add(mod)
        for (_, aid), group in targets.items():
            group.container[aid] = group.apply(group.container.get(aid, 0.0))

    # ------------------------------------------------------------ 输出
    def _finalize(self):
        s = self.sde
        sa = self.ship_attrs

        slots = {"high": [], "med": [], "low": [], "rig": [], "sub": []}
        other = {"charge": [], "drone": [], "implant": [], "booster": [], "cargo": []}
        items = []
        for tid, qty in self.items:
            t = s.types.get(tid, {})
            slot = s.slot_of(tid)
            item = {
                "tid": tid, "name": s.name(tid), "qty": qty,
                "slot": slot, "category_id": t.get("category_id"),
                "group_id": t.get("group_id"),
                "attrs": dict(self.mod_attrs.get(tid, {})),
            }
            items.append(item)
            if slot:
                slots[slot].append(item)
            else:
                cat = t.get("category_id")
                if cat == CAT_CHARGE:
                    key = "charge"
                elif cat == CAT_DRONE or cat == CAT_FIGHTER:
                    key = "drone"
                elif cat == CAT_IMPLANT:
                    key = "booster" if t.get("group_id") == 303 else "implant"
                else:
                    key = "cargo"
                other[key].append(item)

        return {
            "ship": {"tid": self.ship_tid, "name": s.name(self.ship_tid)},
            "skills": dict(self.skills),
            "items": items,
            "slots": slots,
            "other": other,
            **self._panel(sa, slots, other),
        }

    # ------------------------------------------------------------ 面板
    def _panel(self, sa, slots, other):
        s = self.sde
        get = lambda aid, d=0.0: sa.get(aid, d)

        all_slots = (slots["high"] + slots["med"] + slots["low"]
                     + slots["rig"] + slots["sub"])
        pg_used = sum(it["attrs"].get(A_PG_USE, 0.0) * it["qty"] for it in all_slots)
        cpu_used = sum(it["attrs"].get(A_CPU_USE, 0.0) * it["qty"] for it in all_slots)

        turret_list = [it for it in slots["high"] if s.is_weapon(it["tid"])
                       and it["attrs"].get(A_DMG_MULT)]
        launcher_list = [it for it in slots["high"] if s.is_weapon(it["tid"])
                         and it["tid"] not in {x["tid"] for x in turret_list}]
        turret_used = sum(it["qty"] for it in turret_list)
        launcher_used = sum(it["qty"] for it in launcher_list)

        cargo_used = sum(self.sde.types.get(it["tid"], {}).get("volume", 0.0) * it["qty"]
                         for it in other["charge"] + other["cargo"])
        drone_used = sum(self.sde.types.get(it["tid"], {}).get("volume", 0.0) * it["qty"]
                         for it in other["drone"])
        drone_bw_used = sum(it["attrs"].get(A_DRONE_BW, 0.0) for it in other["drone"])

        # ---- 电容
        capacity = get(A_CAP)
        recharge_s = get(A_RECHARGE, 750000.0) / 1000.0
        peak = capacity / recharge_s * 2.5 if recharge_s else 0.0
        drain = 0.0
        for it in all_slots:
            attrs = it["attrs"]
            need = attrs.get(A_NEED, 0.0)
            if need <= 0:
                continue
            cycle_ms = attrs.get(A_DURATION) or attrs.get(A_ROF) or 1000.0
            drain += need / (cycle_ms / 1000.0) * it["qty"]
        stable = drain <= peak
        deplete_s = capacity / (drain - peak) if (not stable and drain > peak) else None

        # ---- 抗性 / EHP
        resists, ehp_layers, ehp_total = {}, {}, 0.0
        layer_hp = {"shield": (get(A_SHIELD_HP), SHIELD_RES),
                    "armor": (get(A_ARMOR_HP), ARMOR_RES),
                    "hull": (get(A_HULL_HP), STRUCT_RES)}
        for layer, (hp, ids) in layer_hp.items():
            res = [sa.get(aid, 1.0) for aid in ids]
            resists[layer] = [round((1 - r) * 100, 1) for r in res]
            ehp = hp / min(res) if res else hp
            ehp_layers[layer] = {"hp": round(hp, 1), "ehp": round(ehp, 1)}
            ehp_total += ehp

        # ---- 火力
        firepower = self._firepower(slots, other)

        # ---- 目标锁定
        sig = get(A_SIGNATURE, 1.0)
        scan_res = get(A_SCAN_RES, 1.0)
        lock_s = 40000.0 / (scan_res * asinh(sig) ** 2) if scan_res > 0 else 0.0

        # ---- 航行
        mass_kg = sa.get(4)
        if not mass_kg:
            mass_kg = self.ship.get("mass", 0.0)
        agility = get(A_AGILITY)
        align_s = mass_kg * agility * ALIGN_FACTOR if agility else 0.0
        warp = get(A_WARP, 0.0) * get(A_WARP_MULT, 1.0)

        # ---- 维修
        rep_armor = sum(it["attrs"].get(A_ARMOR_REPAIR, 0.0) for it in all_slots)
        rep_shield = sum(it["attrs"].get(A_SHIELD_BOOST, 0.0) for it in all_slots)
        cycle = lambda it: (it["attrs"].get(A_DURATION) or 1000.0) / 1000.0
        armor_hps = sum(it["attrs"].get(A_ARMOR_REPAIR, 0.0) / cycle(it)
                        for it in all_slots if it["attrs"].get(A_ARMOR_REPAIR))
        shield_hps = sum(it["attrs"].get(A_SHIELD_BOOST, 0.0) / cycle(it)
                         for it in all_slots if it["attrs"].get(A_SHIELD_BOOST))

        return {
            "resources": {
                "pg": {"used": round(pg_used, 1), "cap": round(get(A_PG), 1)},
                "cpu": {"used": round(cpu_used, 1), "cap": round(get(A_CPU), 1)},
                "turret": {"used": turret_used, "cap": int(get(A_TURRET_HP))},
                "launcher": {"used": launcher_used, "cap": int(get(A_LAUNCHER_HP))},
                "cargo": {"used": round(cargo_used, 1), "cap": round(self.ship.get("capacity", get(A_CARGO)), 1)},
                "drone_bay": {"used": round(drone_used, 1),
                              "cap": round(get(A_DRONE_BAY), 1)},
                "bandwidth": {"used": round(min(drone_bw_used, get(A_DRONE_BW)), 1),
                              "cap": round(get(A_DRONE_BW), 1)},
                "calibration": {"used": sum(it["qty"] for it in slots["rig"]),
                                "cap": int(get(A_CALIBRATION))},
                "slots": {k: len(v) for k, v in slots.items()},
                "slots_cap": {"high": int(get(14)), "med": int(get(13)),
                              "low": int(get(12)), "rig": int(get(1137))},
            },
            "capacitor": {
                "capacity": round(capacity, 1),
                "recharge": round(recharge_s, 1),
                "peak": round(peak, 2),
                "drain": round(drain, 2),
                "stable": stable,
                "deplete": round(deplete_s, 1) if deplete_s else None,
            },
            "resists": resists,
            "ehp": {"layers": ehp_layers, "total": round(ehp_total, 1)},
            "firepower": firepower,
            "targeting": {
                "range": round(get(A_MAX_RANGE), 1),
                "lock_time": round(lock_s, 2),
                "scan_res": round(scan_res, 1),
                "max_targets": int(get(A_MAX_LOCKED)),
                "signature": round(sig, 1),
            },
            "nav": {
                "speed": round(get(A_SPEED), 1),
                "mass": round(mass_kg / 1000.0, 2),
                "agility": round(agility, 4),
                "align": round(align_s, 2),
                "warp": round(warp, 2),
            },
            "repair": {
                "armor": round(armor_hps, 1),
                "shield": round(shield_hps, 1),
            },
        }

    # ------------------------------------------------------------ 火力
    def _charge_item(self, tid):
        """SDE 里的弹药类型 → 与 other["charge"] 同构的条目。

        UI 下拉框列出**全部兼容弹药**（不限于货舱），因此用户可能选中货舱里没有的
        弹药：此时按 SDE 数据算伤害；qty=0 仅表示它不占货舱数量/容积。
        属性优先取自 charge_attrs（含船体/模块加成，与货舱内同款一致）。
        """
        t = self.sde.types.get(tid)
        if not t or t.get("category_id") != CAT_CHARGE:
            return None
        attrs = self.charge_attrs.get(tid) or self.sde.type_attrs.get(tid, {})
        return {"tid": tid, "name": self.sde.name(tid), "qty": 0, "slot": None,
                "category_id": CAT_CHARGE, "group_id": t.get("group_id"),
                "attrs": dict(attrs)}

    def _charge_fits(self, weapon, charge):
        """弹药能否装进该武器：装填尺寸(attr 128)一致 + 弹药组属于 chargeGroup1..5。"""
        a = weapon["attrs"]
        size = a.get(A_CHARGE_SIZE)
        if size is not None and charge["attrs"].get(A_CHARGE_SIZE) != size:
            return False
        allowed = {a[g] for g in A_CHARGE_GROUPS if a.get(g)}
        return not allowed or charge.get("group_id") in allowed

    def _firepower(self, slots, other):
        s = self.sde
        detail = []
        charges = list(other["charge"])
        used_charges = set()

        def pick_charge(weapon, charges, used):
            """给武器配弹药：优先 UI 显式指定的（self.charges）——货舱里有就用那堆，
            没有则按 SDE 数据算（下拉框列出的是全部兼容弹药）；都不符合才自动配：
            先选弹药组匹配的，再退化为仅装填尺寸匹配（旧行为，兼容老装配）。
            显式指定不占用自动配弹名额，允许多门同型武器共用同一弹药堆。"""
            want = self.charges.get(weapon["tid"])
            if want:
                for c in charges:
                    if c["tid"] == want and self._charge_fits(weapon, c):
                        return c
                c = self._charge_item(want)
                if c and self._charge_fits(weapon, c):
                    return c
            size = weapon["attrs"].get(A_CHARGE_SIZE)
            has_groups = any(weapon["attrs"].get(g) for g in A_CHARGE_GROUPS)
            # ① 自动配弹优先「装填尺寸 + 弹药组」都匹配者（尺寸相同但家族不同的弹药不再被误选）
            #    发射架没有装填尺寸属性 → 只按弹药组匹配（否则发射架永远配不到导弹）
            if size is not None or has_groups:
                for i, c in enumerate(charges):
                    if i in used or c["qty"] < weapon["qty"]:
                        continue
                    if self._charge_fits(weapon, c):
                        used.add(i)
                        return c
            # ② 退化：仅按装填尺寸匹配（旧行为；未标注装填尺寸的武器不自动配弹）
            for i, c in enumerate(charges):
                if i in used or c["qty"] < weapon["qty"]:
                    continue
                if size is not None and c["attrs"].get(A_CHARGE_SIZE) == size:
                    used.add(i)
                    return c
            return None

        turret_dps = launcher_dps = 0.0
        turret_volley = launcher_volley = 0.0
        for weapon in slots["high"]:
            if not s.is_weapon(weapon["tid"]):
                continue
            a = weapon["attrs"]
            cycle_s = (a.get(A_ROF) or 1000.0) / 1000.0
            dmg_mult = a.get(A_DMG_MULT, 1.0)
            charge = pick_charge(weapon, charges, used_charges)
            dmg = 0.0
            types = [0.0, 0.0, 0.0, 0.0]
            if charge:
                ca = charge["attrs"]
                types = [ca.get(A_EM, 0.0), ca.get(A_EXPL, 0.0),
                         ca.get(A_KIN, 0.0), ca.get(A_THERM, 0.0)]
            dmg = sum(types) * dmg_mult
            volley = dmg * weapon["qty"]
            dps = volley / cycle_s if cycle_s else 0.0
            if a.get(A_DMG_MULT):
                turret_dps += dps
                turret_volley += volley
            else:
                launcher_dps += dps
                launcher_volley += volley
            detail.append({
                "tid": weapon["tid"], "name": weapon["name"], "qty": weapon["qty"],
                "slot": weapon["slot"],
                "types": [round(t, 1) for t in types],
                "dmg": round(dmg, 1), "volley": round(volley, 1),
                "dps": round(dps, 1), "cycle": round(cycle_s * 1000, 1),
                "optimal": a.get(A_OPTIMAL, 0.0), "falloff": a.get(A_FALLOFF, 0.0),
                "tracking": a.get(160, 0.0), "signature_res": a.get(A_SIG_RES, 0.0),
                "cap_use": round(a.get(A_NEED, 0.0), 1),
                "charge": charge["name"] if charge else None,
                "charge_tid": charge["tid"] if charge else None,
                "charge_size": a.get(A_CHARGE_SIZE),
                "explicit_charge": bool(charge and charge["tid"] == self.charges.get(weapon["tid"])),
            })

        # 无人机（默认全部拉满）
        drones = other["drone"]
        drone_dps = drone_volley = 0.0
        if drones:
            bw_cap = self.ship_attrs.get(A_DRONE_BW, 0.0)
            max_active = int(self.ship_attrs.get(A_MAX_DRONES) or 5)
            n = 0
            per_drone = {}
            for dr in drones:
                a = dr["attrs"]
                bw = a.get(A_DRONE_BW, 0.0)
                if bw_cap and bw * (n + dr["qty"]) > bw_cap:
                    allowed = int((bw_cap - bw * n) // bw) if bw else 0
                    n += max(0, allowed)
                    break
                n += dr["qty"]
            n = min(n, max_active, sum(d["qty"] for d in drones))
            for dr in drones:
                a = dr["attrs"]
                cycle_s = (a.get(A_ROF) or 2000.0) / 1000.0
                dmg = (a.get(A_EM, 0.0) + a.get(A_EXPL, 0.0)
                       + a.get(A_KIN, 0.0) + a.get(A_THERM, 0.0)) * a.get(A_DMG_MULT, 1.0)
                used = min(dr["qty"], n)
                n -= used
                drone_volley += dmg * used
                drone_dps += dmg * used / cycle_s if cycle_s else 0.0
                per_drone[dr["tid"]] = used
        return {
            "turret": {"dps": round(turret_dps, 1), "volley": round(turret_volley, 1)},
            "launcher": {"dps": round(launcher_dps, 1),
                         "volley": round(launcher_volley, 1)},
            "drone": {"dps": round(drone_dps, 1), "volley": round(drone_volley, 1)},
            "total": round(turret_dps + launcher_dps + drone_dps, 1),
            "weapons": detail,
        }


def simulate(sde, ship_tid, modules, skills=None, charges=None):
    """便捷入口：sde 为 StaticData 实例；charges=每门武器的显式弹药选择。"""
    return Fit(sde, ship_tid, modules, skills, charges).solve()