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