"""逐门武器的弹药列表：GET /api/weapon/<tid>/charges 接口契约 + 引擎一致性。

背景：弹药下拉框要列出该武器的**全部兼容弹药**（不限于装配/货舱里已有的），
后端按 SDE 的装填尺寸(attr 128) + 允许弹药组 chargeGroup1..5(attr 604-608) 计算。
运行：python3 -m pytest tests/test_ammo.py -q
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webapp  # noqa: E402
from engine.data import StaticData  # noqa: E402
from engine.simulate import simulate  # noqa: E402

SDE = StaticData()
PROPHECY = 16233    # 先知级
PULSE2 = 3520       # 重型脉冲激光器 II（装填尺寸 2，允许组：频率晶体 / 高级脉冲激光晶体）
LIGHT_LAUNCHER = 499   # 轻型导弹发射器 I（无装填尺寸，只有弹药组 384 轻型导弹 / 394 自动锁定轻型导弹）
MULTI_M = 254       # 多频晶体 M
RADIO_M = 247       # 射频晶体 M
HYBRID_M = 223      # 铁质轨道弹 M（混合弹药：尺寸同为 2 但弹药组不符）


@pytest.fixture
def client():
    return webapp.app.test_client()


def charges(client, tid):
    resp = client.get(f"/api/weapon/{tid}/charges")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_lists_all_compatible_charges(client):
    """全部兼容弹药：尺寸一致、弹药组属武器、件件有伤害（脚本类无伤害不入选）。"""
    lst = charges(client, PULSE2)
    tids = {c["tid"] for c in lst}
    assert len(lst) >= 40                                        # 远超货舱里常见的几种
    assert {MULTI_M, RADIO_M} <= tids
    assert HYBRID_M not in tids                                   # 弹药组不符
    assert all(c["size"] == 2 and sum(c["damage"]) > 0 for c in lst)
    assert {c["group"] for c in lst} == {"频率晶体", "高级脉冲激光晶体"}
    assert {c["meta"] for c in lst} == {1, 2, 4}                  # T1 / T2 / 势力
    assert all(c["meta_label"] and c["name"] and c["group"] for c in lst)


def test_non_weapon_lists_nothing(client):
    assert charges(client, PROPHECY) == []                        # 舰船
    assert charges(client, 34) == []                              # 三钛合金（矿物）
    assert charges(client, 99999999) == []                        # 不存在的类型


def test_result_cached_per_weapon(client):
    """SDE 运行期不变 → 结果按武器 tid 缓存，重复请求直接命中。"""
    first = charges(client, PULSE2)
    assert webapp._weapon_charges_cache.get(PULSE2) == first
    assert charges(client, PULSE2) == first


def test_selected_charge_needs_no_cargo():
    """选中列表里的弹药即可生效——货舱里没有也一样（此前会回退成自动配弹）。"""
    items = [(PULSE2, 1), (MULTI_M, 100)]
    base = simulate(SDE, PROPHECY, items)
    r = simulate(SDE, PROPHECY, items, None, {PULSE2: RADIO_M})
    w = r["firepower"]["weapons"][0]
    assert (w["charge_tid"], w["explicit_charge"]) == (RADIO_M, True)
    assert all(it["tid"] != RADIO_M for it in r["items"])          # 确实不在货舱
    assert r["resources"]["cargo"]["used"] == base["resources"]["cargo"]["used"]


def test_every_listed_charge_is_engine_accepted(client):
    """列表与引擎共用同一套匹配规则：任列出的弹药作显式选择都被采纳，伤害取该弹药。"""
    lst = charges(client, PULSE2)
    for c in lst[:5] + lst[-5:]:
        r = simulate(SDE, PROPHECY, [(PULSE2, 1)], None, {PULSE2: c["tid"]})
        w = r["firepower"]["weapons"][0]
        assert (w["charge_tid"], w["charge"]) == (c["tid"], c["name"])
        assert w["explicit_charge"] is True
        assert w["types"] == c["damage"]                           # EM/爆炸/动能/热能


def test_missile_launcher_lists_its_own_family(client):
    """发射架没有装填尺寸属性(attr 128) → 退化为只按弹药组匹配，且不含炮弹/晶体。

    注：导弹/发射架尚未纳入火力面板（`is_weapon` 只认炮台类效果），故此处只校验
    接口与兼容性判定；「选中即生效」由炮台用例 test_selected_charge_needs_no_cargo 覆盖。
    """
    lst = charges(client, LIGHT_LAUNCHER)
    assert len(lst) >= 20
    assert {c["group"] for c in lst} == {"轻型导弹", "自动锁定轻型导弹"}
    assert all(sum(c["damage"]) > 0 for c in lst)
    assert not ({c["tid"] for c in lst} & {MULTI_M, RADIO_M, HYBRID_M})
    assert SDE.charge_compatible(LIGHT_LAUNCHER, lst[0]["tid"]) is True
    assert SDE.charge_compatible(LIGHT_LAUNCHER, HYBRID_M) is False
