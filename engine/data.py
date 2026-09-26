"""加载本地 SDE 索引（SQLite）进内存，供热配模拟引擎使用。

数据由 build_index.py 从官方 SDE JSONL 构建；全部离线。
"""

import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "staticdata.db")


def _zh_text(dn):
    """SDE 的 displayName/描述 是 多语言 dict 的 JSON 文本，取中文。"""
    if not dn:
        return ""
    if isinstance(dn, str):
        try:
            dn = json.loads(dn)
        except ValueError:
            return dn
    return dn.get("zh") or dn.get("en") or ""


# 弹药匹配相关属性：武器 → 允许的弹药组 chargeGroup1..5；弹药 → 装填尺寸/伤害
A_CHARGE_SIZE = 128
A_CHARGE_GROUPS = (604, 605, 606, 607, 608)
A_CHARGE_DAMAGE = (114, 116, 117, 118)      # EM / 爆炸 / 动能 / 热能
CAT_CHARGE = 8

# 弹药 meta 等级 → 展示标签（弹药下拉框在名称后标注）
META_LABELS = {1: "T1", 2: "T2", 3: "故事线", 4: "势力", 5: "官员", 6: "死亡空间",
               8: "标准", 14: "T3"}


def ammo_family(group_name):
    """从弹药组名提取家族名：去掉 高级/自动锁定/超大型/势力/建筑 等前缀。"""
    for pfx in ("高级超大型", "高级", "自动锁定", "势力", "建筑", "超大型"):
        if group_name.startswith(pfx):
            return group_name[len(pfx):]
    return group_name


class StaticData:
    """一次性把配置相关的 SDE 数据载入内存（应用启动时构建一次）。"""

    def __init__(self, db_path=DB_PATH):
        conn = sqlite3.connect(db_path)
        try:
            self._load(conn)
        finally:
            conn.close()

    def _load(self, conn):
        self.types = {}
        for row in conn.execute("SELECT type_id,group_id,category_id,name,name_en,"
                                "published,volume,capacity,mass,meta_group_id,"
                                "market_group_id,race_id FROM types"):
            tid, gid, cat, name, en, pub, vol, cap, mass, meta, market, race = row
            self.types[tid] = {
                "id": tid, "group_id": gid, "category_id": cat,
                "name": name, "name_en": en, "published": bool(pub),
                "volume": vol, "capacity": cap, "mass": mass,
                "meta_group_id": meta, "market_group_id": market,
                "race_id": race,
            }

        self.races = {}
        for rid, name in conn.execute("SELECT race_id,name FROM races"):
            self.races[rid] = name

        self.groups = {}
        for gid, cat, name in conn.execute("SELECT group_id,category_id,name FROM groups"):
            self.groups[gid] = {"id": gid, "category_id": cat, "name": name}

        self.attrs = {}
        for aid, name, dn, uid in conn.execute(
                "SELECT attribute_id,name,display_name,unit_id FROM attrs"):
            self.attrs[aid] = {"id": aid, "name": name,
                               "display_name": _zh_text(dn), "unit_id": uid}

        self.units = {}
        for uid, name, dn in conn.execute("SELECT unit_id,name,display_name FROM units"):
            self.units[uid] = {"id": uid, "name": name,
                               "display_name": _zh_text(dn)}

        self.effects = {}
        for eid, name, cat, discharge, dur, rng, offensive, assist, mi in conn.execute(
                "SELECT effect_id,name,effect_category,discharge_attribute_id,"
                "duration_attribute_id,range_attribute_id,is_offensive,"
                "is_assistance,modifier_info FROM effects"):
            self.effects[eid] = {
                "id": eid, "name": name, "category": cat,
                "discharge": discharge, "duration": dur, "range": rng,
                "offensive": bool(offensive), "assistance": bool(assist),
                "modifiers": json.loads(mi or "[]"),
            }

        self.type_attrs = {}
        for tid, aid, val in conn.execute("SELECT type_id,attribute_id,value FROM type_attrs"):
            self.type_attrs.setdefault(tid, {})[aid] = val

        # 弹药索引：已发布、带伤害属性的 cat8 弹药（脚本/电容注电器装料/扫描探针等
        # 无伤害「弹药」不算可选弹药，天然被排除）。按装填尺寸分桶；发射架类武器没有
        # 装填尺寸属性(attr 128)，只能按弹药组匹配，故另存全量表 damage_charges。
        self.damage_charges = []
        self.charges_by_size = {}
        for tid, t in self.types.items():
            if t["category_id"] != CAT_CHARGE or not t["published"]:
                continue
            attrs = self.type_attrs.get(tid, {})
            if not any(attrs.get(a, 0.0) > 0 for a in A_CHARGE_DAMAGE):
                continue
            self.damage_charges.append(tid)
            size = attrs.get(A_CHARGE_SIZE)
            if size is not None:
                self.charges_by_size.setdefault(size, []).append(tid)

        self.type_effects = {}
        for tid, eid, isdef in conn.execute(
                "SELECT type_id,effect_id,is_default FROM type_effects"):
            self.type_effects.setdefault(tid, {})[eid] = bool(isdef)

        self.traits = {}
        for tid, bonus in conn.execute("SELECT type_id,bonus_json FROM type_bonuses"):
            self.traits[tid] = json.loads(bonus)

    # ------------------------------------------------------------ 便捷查询
    def name(self, tid):
        t = self.types.get(tid)
        return t["name"] if t else str(tid)

    def attr(self, tid, aid, default=None):
        return self.type_attrs.get(tid, {}).get(aid, default)

    def group_name(self, gid):
        g = self.groups.get(gid)
        return g["name"] if g else str(gid)

    def race_name(self, tid):
        """舰船种族中文名（SDE 未标注 raceID 的类型归入「其他」）。"""
        t = self.types.get(tid)
        rid = t.get("race_id") if t else None
        return self.races.get(rid) or "其他"

    def slot_of(self, tid):
        """由物品的效果判定槽位：high/med/low/rig/sub/None。"""
        fx = self.type_effects.get(tid, {})
        for eid in fx:
            name = self.effects.get(eid, {}).get("name", "")
            if name == "hiPower":
                return "high"
            if name == "medPower":
                return "med"
            if name == "loPower":
                return "low"
            if name == "rigSlot":
                return "rig"
            if name == "subSystem":
                return "sub"
        return None

    def is_weapon(self, tid):
        """炮台/发射架类武器（伤害相关，可输出 DPS 的高槽装备）。"""
        fx = self.type_effects.get(tid, {})
        for eid in fx:
            eff = self.effects.get(eid, {})
            if eff.get("offensive") or eff.get("category") == 2:
                return True
        return False

    # ------------------------------------------------------------ 弹药匹配
    def charge_compatible(self, weapon_tid, charge_tid):
        """弹药能否装进该武器：装填尺寸(attr 128)一致 + 弹药组属于 chargeGroup1..5。

        两项武器都没标注时视为不限（老式/特殊武器）；发射架只有弹药组没有装填尺寸，
        此时只校验弹药组。与 Fit._charge_fits 同一套规则。
        """
        w = self.type_attrs.get(weapon_tid, {})
        size = w.get(A_CHARGE_SIZE)
        if size is not None and self.type_attrs.get(charge_tid, {}).get(A_CHARGE_SIZE) != size:
            return False
        allowed = {w[a] for a in A_CHARGE_GROUPS if w.get(a)}
        if not allowed:
            return True
        t = self.types.get(charge_tid)
        return t is not None and t["group_id"] in allowed

    def charges_for(self, weapon_tid):
        """该武器可装填的**全部**弹药（SDE 全量，不限于装配/货舱里已有的）。

        规则：已发布 cat8 弹药 + 有伤害属性（排除脚本/电容注电器装料/扫描探针等）
        + 弹药组属于武器 chargeGroup1..5 + 装填尺寸与武器一致；发射架类武器没有
        装填尺寸属性 → 退化为只按弹药组匹配（同理，武器未标注弹药组时只按尺寸）。
        返回按「弹药组 → meta 等级 → 名称」排序的列表，供 UI 下拉框分组展示。
        """
        w = self.type_attrs.get(weapon_tid, {})
        size = w.get(A_CHARGE_SIZE)
        allowed = {w[a] for a in A_CHARGE_GROUPS if w.get(a)}
        if size is None and not allowed:
            return []                       # 既无装填尺寸也无弹药组 → 无从判断
        pool = self.charges_by_size.get(size, []) if size is not None else self.damage_charges
        out = []
        for tid in pool:
            t = self.types[tid]
            if allowed and t["group_id"] not in allowed:
                continue
            attrs = self.type_attrs.get(tid, {})
            group = self.group_name(t["group_id"])
            out.append({
                "tid": tid, "name": t["name"], "name_en": t["name_en"],
                "group_id": t["group_id"], "group": group,
                "family": ammo_family(group), "meta": t.get("meta_group_id"),
                "meta_label": META_LABELS.get(t.get("meta_group_id"), ""),
                "size": attrs.get(A_CHARGE_SIZE),
                "damage": [round(attrs.get(a, 0.0), 1) for a in A_CHARGE_DAMAGE],
            })
        out.sort(key=lambda c: (c["group"], c["meta"] or 0, c["name"]))
        return out