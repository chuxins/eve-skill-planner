"""测试全局安全网：**任何测试都不得改动真实的 token 目录**。

背景：真实凭据在 ~/.eve-skill-planner/tokens/，一旦用例误用未打补丁的 config.TOKEN_DIR
（或忘记用 tests/test_logout.py 的 tokens fixture），esi.forget* 会删掉真实 token —— 且不可恢复。
本 fixture 在会话前后比对真实目录内容，发现变化即让整个测试会话失败。
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402


def _snapshot(path):
    try:
        return sorted(p.name for p in Path(path).iterdir())
    except OSError:
        return []


@pytest.fixture(scope="session", autouse=True)
def guard_real_token_dir():
    """会话级：真实 token 目录内容必须原样不变（真实路径在 monkeypatch 之前取）。"""
    real = os.path.join(config.LEGACY_DATA, "tokens")
    before = _snapshot(real)
    yield
    after = _snapshot(real)
    assert after == before, (
        f"测试改动了真实 token 目录 {real}！\n"
        f"  消失：{sorted(set(before) - set(after))}\n  新增：{sorted(set(after) - set(before))}\n"
        "请检查用例是否漏打 config.TOKEN_DIR 补丁（见 tests/test_logout.py 的 tokens fixture）。"
    )
