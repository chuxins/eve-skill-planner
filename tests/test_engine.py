"""引擎回归测试：断言锚定 pyfa/游戏实测数值。

运行：python3 -m pytest tests/test_engine.py  （或 python3 tests/test_engine.py）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data import StaticData
from engine.simulate import simulate

SDE = StaticData()
PROPHECY = 16233   # 先知级


def approx(a, b, tol=0.15):
    return abs(a - b) <= tol


def test_empty_ship():
    r = simulate(SDE, PROPHECY, [])
    assert r["resources"]["pg"]["cap"] == 1100.0
    assert r["resources"]["cpu"]["cap"] == 415.0
    assert r["capacitor"]["capacity"] == 3000.0
    assert r["capacitor"]["recharge"] == 750.0
    assert r["resists"]["armor"] == [50.0, 20.0, 25.0, 35.0]
    assert r["resists"]["shield"] == [0.0, 50.0, 40.0, 20.0]
    assert r["resists"]["hull"] == [33.0, 33.0, 33.0, 33.0]
    assert approx(r["ehp"]["total"], 22970.1)
    assert approx(r["nav"]["align"], 12.09)


def test_skills_pgm_capops():
    r = simulate(SDE, PROPHECY, [], skills={3413: 5})   # 能量栅格管理学 V
    assert r["resources"]["pg"]["cap"] == 1375.0
    r = simulate(SDE, PROPHECY, [], skills={3417: 5})   # 电容系统操作 V
    assert r["capacitor"]["recharge"] == 562.5


def test_damage_control():
    r = simulate(SDE, PROPHECY, [(2048, 1)])            # 损伤控制 II
    assert r["resists"]["hull"] == [59.8, 59.8, 59.8, 59.8]
    assert r["resists"]["armor"][0] == 57.5             # EM 装甲 0.5→×0.85
    assert r["resists"]["shield"][0] == 12.5            # EM 护盾 1.0→×0.875


def test_cap_recharger_stack():
    r1 = simulate(SDE, PROPHECY, [(2032, 1)])           # 电容回充器 II
    assert r1["capacitor"]["recharge"] == 600.0
    r2 = simulate(SDE, PROPHECY, [(2032, 2)])           # 豁免堆叠惩罚
    assert r2["capacitor"]["recharge"] == 480.0
    r3 = simulate(SDE, PROPHECY, [(2032, 1)], skills={3417: 5})
    assert r3["capacitor"]["recharge"] == 450.0


def test_hardener_stacking():
    r = simulate(SDE, PROPHECY, [(11642, 2)])           # 2×电磁装甲增强器 II
    assert approx(r["resists"]["armor"][0], 88.3)       # 第二个按 86.9% 惩罚


def test_battery_flat_add():
    r = simulate(SDE, PROPHECY, [(3496, 1)])            # 中型电容器电池 II
    assert r["capacitor"]["capacity"] == 3625.0         # 3500 + 125


def test_executor_prop_mods():
    import math
    base_agi = SDE.attr(11393, 70)
    r = simulate(SDE, 11393, [(5973, 1)], skills={3417: 5})    # 审判者级 + 5MN Y-T8
    assert approx(r["nav"]["agility"], base_agi * 1.125, 0.01)  # MWD 惯性惩罚
    assert r["nav"]["mass"] == 1053.9 + 500.0                   # +500t（截图锚定）
    expect_align = (1053.9 + 500.0) * 1000 * base_agi * 1.125 * math.log(4) / 1e6
    assert approx(r["nav"]["align"], expect_align, 0.01)


PULSE2 = 3520       # 重型脉冲激光器 II（装填尺寸 2 = 中型）
MULTI_M = 254       # 多频晶体 M（高伤）
RADIO_M = 247       # 射频晶体 M（低伤远距）
MULTI_S = 246       # 多频晶体 S（装填尺寸 1，用于尺寸不符回退）
HYBRID_M = 223      # 铁质轨道弹 M（混合弹药：尺寸同为 2 但弹药组不符，也须回退）
LAUNCHER = 499      # 轻型导弹发射器 I（无装填尺寸，只有弹药组 384/394 → 只按弹药组配弹）
KIN_MISSILE = 210   # 鞭挞轻型导弹（动能 83）
TORP_LAUNCHER = 503   # 鱼雷发射器 I
TORP = 267          # 鞭挞鱼雷（动能 450）
SIEGE2 = 4292       # 会战装备 II（shipID 域修正鱼雷弹药伤害 → 450×3=1350，用于加成等价性）


def test_charge_auto_and_explicit():
    """弹药：未指定时按装填尺寸自动配，指定时以指定者为准。"""
    base = [(PULSE2, 1), (MULTI_M, 100), (RADIO_M, 100)]
    auto = simulate(SDE, PROPHECY, base)
    w = auto["firepower"]["weapons"][0]
    assert w["charge_size"] == 2.0                      # 炮的装填尺寸
    assert w["charge"] == "多频晶体 M" and w["charge_tid"] == MULTI_M
    assert w["explicit_charge"] is False
    assert auto["firepower"]["turret"]["dps"] == 16.5
    r = simulate(SDE, PROPHECY, base, None, {PULSE2: RADIO_M})   # 显式换成射频晶体
    w2 = r["firepower"]["weapons"][0]
    assert w2["charge"] == "射频晶体 M" and w2["charge_tid"] == RADIO_M
    assert w2["explicit_charge"] is True
    assert r["firepower"]["turret"]["dps"] == 6.9
    assert r["firepower"]["turret"]["dps"] < auto["firepower"]["turret"]["dps"]


def test_charge_explicit_outside_cargo():
    """下拉框列出「全部兼容弹药」→ 选中货舱里没有的弹药也要生效（按 SDE 算伤害）。"""
    items = [(PULSE2, 1), (MULTI_M, 100)]
    base = simulate(SDE, PROPHECY, items)
    r = simulate(SDE, PROPHECY, items, None, {PULSE2: RADIO_M})   # 射频晶体不在装配里
    w = r["firepower"]["weapons"][0]
    assert all(it["tid"] != RADIO_M for it in r["items"])          # 确实没装进货舱
    assert w["charge"] == "射频晶体 M" and w["charge_tid"] == RADIO_M
    assert w["explicit_charge"] is True
    assert r["firepower"]["turret"]["dps"] == 6.9                  # 与货舱里有同款弹药一致
    assert r["resources"]["cargo"]["used"] == base["resources"]["cargo"]["used"]  # 不占货舱


def test_charge_falls_back_when_invalid():
    """显式弹药尺寸不符 / 弹药组不符 / 类型不存在 → 回退自动配弹，不报错。"""
    items = [(PULSE2, 1), (MULTI_M, 100)]
    for bad in (MULTI_S, HYBRID_M, 99999999):
        r = simulate(SDE, PROPHECY, items, None, {PULSE2: bad})
        w = r["firepower"]["weapons"][0]
        assert w["charge"] == "多频晶体 M" and w["explicit_charge"] is False


def test_auto_charge_prefers_matching_group():
    """货舱里混有尺寸相同的别家族弹药 → 自动配弹优先弹药组匹配者（不受顺序影响）。"""
    r = simulate(SDE, PROPHECY, [(PULSE2, 1), (HYBRID_M, 100), (MULTI_M, 100)])
    w = r["firepower"]["weapons"][0]
    assert w["charge_tid"] == MULTI_M and w["explicit_charge"] is False


def test_charges_for_weapon_lists_all_compatible():
    """SDE 兼容弹药表：尺寸一致、弹药组属于武器 chargeGroup1..5、件件有伤害。"""
    lst = SDE.charges_for(PULSE2)
    tids = {c["tid"] for c in lst}
    assert len(lst) >= 40                                        # 含 T1/T2/势力，远多于货舱所见
    assert {MULTI_M, RADIO_M} <= tids
    assert HYBRID_M not in tids and MULTI_S not in tids           # 弹药组/尺寸不符
    assert all(c["size"] == 2 and sum(c["damage"]) > 0 for c in lst)   # 脚本类无伤害 → 不在表内
    assert {c["group"] for c in lst} == {"频率晶体", "高级脉冲激光晶体"}
    assert SDE.charges_for(PROPHECY) == []                        # 舰船没有可装弹药
    assert SDE.charge_compatible(PULSE2, RADIO_M) is True
    assert SDE.charge_compatible(PULSE2, HYBRID_M) is False


def test_charge_explicit_ignores_qty_gate():
    """自动配弹要求弹药数量≥武器数量；显式指定不做该限制（1 发也能打）。"""
    items = [(PULSE2, 1), (RADIO_M, 1)]
    r = simulate(SDE, PROPHECY, items, None, {PULSE2: RADIO_M})
    assert r["firepower"]["weapons"][0]["charge"] == "射频晶体 M"
    assert r["firepower"]["weapons"][0]["explicit_charge"] is True


def test_launcher_is_weapon_and_gets_ammo():
    """发射架纳入武器：进火力面板（有行内弹药下拉框）、占发射位、按弹药组自动配弹。"""
    assert SDE.is_weapon(LAUNCHER) and SDE.slot_of(LAUNCHER) == "high"
    assert SDE.is_weapon(TORP_LAUNCHER)
    assert not SDE.is_weapon(5973)                     # 5MN Y-T8 微型跃迁推进器
    assert not SDE.is_weapon(PROPHECY)                 # 舰船
    items = [(LAUNCHER, 2), (KIN_MISSILE, 100)]
    auto = simulate(SDE, PROPHECY, items)
    w = auto["firepower"]["weapons"][0]
    assert w["charge"] == "鞭挞轻型导弹" and w["charge_tid"] == KIN_MISSILE
    assert w["charge_size"] is None                    # 发射架没有装填尺寸
    assert w["types"] == [0.0, 0.0, 83.0, 0.0]         # 伤害取导弹
    assert auto["firepower"]["launcher"]["dps"] == 10.4     # 83 × 2 / 16s
    assert auto["firepower"]["turret"]["dps"] == 0.0        # 发射架不计入炮台
    assert auto["firepower"]["total"] == 10.4
    assert auto["resources"]["launcher"]["used"] == 2       # 占发射位（旧行为记 0）
    r = simulate(SDE, PROPHECY, [(LAUNCHER, 2)], None, {LAUNCHER: KIN_MISSILE})
    assert r["firepower"]["weapons"][0]["explicit_charge"] is True
    assert r["firepower"]["launcher"]["dps"] == auto["firepower"]["launcher"]["dps"]
    assert all(it["tid"] != KIN_MISSILE for it in r["items"])    # 不进货舱


def test_launcher_without_ammo():
    """发射架没配到弹药 → 照常出现在武器行（UI 提示「无弹药」），DPS 为 0。"""
    w = simulate(SDE, PROPHECY, [(LAUNCHER, 2)])["firepower"]["weapons"][0]
    assert w["charge"] is None and w["dps"] == 0.0 and w["cycle"] == 16000.0


def test_explicit_charge_gets_same_bonuses_as_cargo():
    """货舱里没有的弹药也必须吃到同样的船体/模块加成（否则同款弹药两个伤害）。

    会战装备 II 的修正作用在**弹药**属性上（450 → 1350）；若显式弹药不走同一
    套修正管线，从下拉框选它就只能算 450（dps 25.0 而非 75.0）。
    """
    in_cargo = simulate(SDE, PROPHECY, [(TORP_LAUNCHER, 1), (TORP, 100), (SIEGE2, 1)])
    w = in_cargo["firepower"]["weapons"][0]
    assert w["types"] == [0.0, 0.0, 1350.0, 0.0] and w["dps"] == 75.0
    outside = simulate(SDE, PROPHECY, [(TORP_LAUNCHER, 1), (SIEGE2, 1)],
                       None, {TORP_LAUNCHER: TORP})["firepower"]["weapons"][0]
    assert outside["explicit_charge"] is True
    assert outside["types"] == w["types"] and outside["dps"] == w["dps"]


def test_virtual_charge_bonus_applies_only_to_virtual():
    """`_apply(extra=...)` 只作用于虚拟弹药容器——绝不把修正重复施加到装配内物品。"""
    from engine.simulate import Fit, Modifier
    fit = Fit(SDE, PROPHECY, [(LAUNCHER, 1)])
    fit.mod_attrs[LAUNCHER][117] = 10.0
    virtual = {KIN_MISSILE: dict(SDE.type_attrs[KIN_MISSILE])}
    fit._apply([Modifier("shipID", "LocationGroupModifier", 117, 7, 25.0, "module",
                         False, group_id=384)], extra=virtual)
    assert virtual[KIN_MISSILE][117] == 83.0 * 1.25    # 虚拟弹药吃到 +25%
    assert fit.mod_attrs[LAUNCHER][117] == 10.0        # 装配内物品未被重复加成


def test_eft_Parser():
    from engine.eft import parse_eft, render_eft
    ship, fit, items = parse_eft("[先知级, 测试]\n损伤控制 II\n损伤控制 II\n[Empty Low slot]\n散弹S x2\n")
    assert ship == "先知级" and fit == "测试"
    assert items == [("损伤控制 II", 1), ("损伤控制 II", 1), ("散弹S", 2)]
    out = render_eft("先知级", "测试", items)
    assert "[先知级, 测试]" in out and "散弹S x2" in out


if __name__ == "__main__":
    fn = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = []
    for name, f in fn:
        try:
            f()
            print(f"PASS {name}")
        except AssertionError as exc:
            fails.append(name)
            print(f"FAIL {name}: {exc}")
    print(f"\n{len(fn) - len(fails)}/{len(fn)} 通过")
    sys.exit(1 if fails else 0)