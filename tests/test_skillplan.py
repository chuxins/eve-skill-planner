"""技能规划引擎测试：SP 公式、需求技能闭包、拓扑顺序、训练时间。

运行：python3 -m pytest tests/test_skillplan.py  （或 python3 tests/test_skillplan.py）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data import StaticData
from engine.skillplan import (build_plan, collect_requirements, skill_time,
                              sp_to_level)

SDE = StaticData()
PROPHECY = 16233            # 先知级（需求：艾玛战列巡洋舰操作 I）
AMARR_BC = 33095            # 艾玛战列巡洋舰操作（rank 6；需求：飞船操控学 III 等）
SPACESHIP_CMD = 3327        # 飞船操控学（无前置）
DC2 = 2048                  # 损伤控制 II（需求：机械学 IV）
MECHANICS = 3394            # 机械学

A24 = {"perception": 24, "willpower": 24, "intelligence": 23, "memory": 24,
       "charisma": 22}      # 实测 chuxins1 的有效属性


def approx(a, b, tol=0.5):
    return abs(a - b) <= tol


def test_sp_table():
    """rank 1 各级累计技能点（游戏已知值）。"""
    assert sp_to_level(1, 1) == 250.0
    assert approx(sp_to_level(1, 2), 1414.2)
    assert approx(sp_to_level(1, 3), 8000.0)
    assert approx(sp_to_level(1, 4), 45254.8)
    assert approx(sp_to_level(1, 5), 256000.0)
    assert sp_to_level(1, 0) == 0.0
    assert approx(sp_to_level(6, 3), 48000.0)      # rank 线性放大


def test_collect_requirements_recurses_prereqs():
    reqs = collect_requirements(SDE, [PROPHECY])
    assert reqs[AMARR_BC] == 1                     # 舰船直接需求
    assert reqs[SPACESHIP_CMD] == 3                # 前置技能（递归展开）
    assert MECHANICS not in reqs                   # 与舰船无关的技能不应出现


def test_requirements_include_fit_modules():
    reqs = collect_requirements(SDE, [PROPHECY, DC2])
    assert reqs[MECHANICS] == 4                    # 损伤控制 II 的机械学 IV


def test_topological_order_prereq_first():
    plan = build_plan(SDE, PROPHECY, [], {}, A24)
    order = [r["tid"] for r in plan["requirements"]]
    assert order.index(SPACESHIP_CMD) < order.index(AMARR_BC)


def test_training_time_matches_formula():
    # rank 6 技能 0→3：SP=48000，速率=24+24/2=36 SP/min → 80000 s
    assert approx(skill_time(SDE, AMARR_BC, 0, 3, A24), 80000.0, 1.0)
    # 已达标（to<=from）返回 0
    assert skill_time(SDE, AMARR_BC, 3, 3, A24) == 0.0
    # 属性缺省回退基础 17 → 更慢
    assert skill_time(SDE, AMARR_BC, 0, 3, None) > 80000.0
    # 只练一级（0→1，rank 6）：SP=1500，1500/36*60=2500 s
    assert approx(skill_time(SDE, AMARR_BC, 0, 1, A24), 2500.0, 0.5)


def test_build_plan_all_trained_has_no_gap():
    skills = {r["tid"]: 5 for r in
              build_plan(SDE, PROPHECY, [DC2], {}, A24)["requirements"]}
    plan = build_plan(SDE, PROPHECY, [DC2], skills, A24)
    assert plan["missing"] == []
    assert plan["total_seconds"] == 0.0
    assert all(r["ok"] for r in plan["requirements"])


def test_build_plan_reports_gaps_and_total():
    plan = build_plan(SDE, PROPHECY, [DC2], {}, A24)
    missing = {r["tid"]: r for r in plan["missing"]}
    assert AMARR_BC in missing and SPACESHIP_CMD in missing
    assert MECHANICS in missing and missing[MECHANICS]["required"] == 4
    assert missing[AMARR_BC]["current"] == 0
    assert plan["total_seconds"] == round(
        sum(r["seconds"] or 0 for r in plan["missing"]), 1)
    assert plan["total_seconds"] > 0
    assert plan["ship"] == {"tid": PROPHECY, "name": "先知级"}


def test_build_plan_partial_levels_only_counts_remainder():
    full = build_plan(SDE, PROPHECY, [DC2], {}, A24)
    partial_skills = {AMARR_BC: 1}                 # 战列巡洋舰操作已 1 级
    plan = build_plan(SDE, PROPHECY, [DC2], partial_skills, A24)
    missing = {r["tid"]: r for r in plan["missing"]}
    assert AMARR_BC not in missing                 # 需求 1 级已满足
    assert SPACESHIP_CMD in missing                # 前置仍需 3 级
    assert plan["total_seconds"] < full["total_seconds"]


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
