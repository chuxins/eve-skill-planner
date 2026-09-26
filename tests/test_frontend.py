"""前端静态检查（无构建步骤，故用手动检查兜底）。

运行：python3 -m pytest tests/test_frontend.py   （缺 node 时整文件跳过）
"""

import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="未安装 node")


def test_frontend_static_checks():
    """JS 语法 + Vue 模板编译 + 资源版本占位（见 tests/check_frontend.js）。"""
    proc = subprocess.run(["node", os.path.join(ROOT, "tests", "check_frontend.js")],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_logout_flow_behavior():
    """退出登录行为：只注销当前角色、页头直接变「登录」、不自动切换（见 tests/logoutflow.js）。"""
    proc = subprocess.run(["node", os.path.join(ROOT, "tests", "logoutflow.js")],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_index_injects_asset_version_and_favicon():
    """首页渲染时替换 {{ASSET_VERSION}}，且 favicon/静态资源可访问。"""
    import webapp
    client = webapp.app.test_client()
    html = client.get("/").get_data(as_text=True)
    assert "{{ASSET_VERSION}}" not in html
    assert "/static/util.js?v=" in html and "/static/app.js?v=" in html
    assert "favicon.svg?v=" in html
    assert client.get("/static/util.js").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/favicon.svg").status_code == 200
    assert client.get("/favicon.ico").status_code == 204
