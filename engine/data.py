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
                                "market_group_id FROM types"):
            tid, gid, cat, name, en, pub, vol, cap, mass, meta, market = row
            self.types[tid] = {
                "id": tid, "group_id": gid, "category_id": cat,
                "name": name, "name_en": en, "published": bool(pub),
                "volume": vol, "capacity": cap, "mass": mass,
                "meta_group_id": meta, "market_group_id": market,
            }

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