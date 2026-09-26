"""退出登录：token 文件删除 / 内存缓存清理 / 接口契约。

全部用例把 TOKEN_DIR 指向临时目录并桩掉 SSO 吊销，**不触网、不碰真实 token**。
运行：python3 -m pytest tests/test_logout.py -q
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
import esi  # noqa: E402


@pytest.fixture
def tokens(tmp_path, monkeypatch):
    """临时 token 目录 + 无网络：111 小号甲 / 222 小号乙。"""
    monkeypatch.setattr(config, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(config, "LEGACY_DATA", str(tmp_path))   # 隔离 CLI token.json 回退
    monkeypatch.setattr(esi, "revoke", lambda token: True)
    monkeypatch.setattr(esi, "_cache", {111: ({"id": 111, "name": "小号甲"}, 0)})
    for cid, name in ((111, "小号甲"), (222, "小号乙")):
        (tmp_path / f"{cid}.json").write_text(json.dumps(
            {"id": cid, "name": name, "access_token": "a", "refresh_token": "r"}))
    return tmp_path


def test_forget_one_character(tokens):
    """注销单个角色：删其文件、清其缓存，其余角色不受影响。"""
    got = esi.forget(111)
    assert (got["id"], got["name"], got["removed"], got["revoked"]) == (111, "小号甲", True, True)
    assert got["note"] is None
    assert not (tokens / "111.json").exists()
    assert (tokens / "222.json").exists()
    assert esi._cache == {}
    assert [c["id"] for c in esi.list_characters()] == [222]


def test_forget_all_clears_everything(tokens):
    """退出登录（全部）：tokens/ 清空 + 缓存清空 + 角色列表为空。"""
    results = esi.forget_all()
    assert [r["id"] for r in results] == [111, 222]
    assert all(r["removed"] for r in results)
    assert list(tokens.glob("*.json")) == []
    assert esi._cache == {}
    assert [c["id"] for c in esi.list_characters()] == []
    assert esi.forget_all() == []          # 幂等：已无 token 时不报错


def test_forget_unknown_cid_is_safe(tokens):
    """未授权角色：不报错，仅提示（removed=False）。"""
    got = esi.forget(999)
    assert got["removed"] is False and got["revoked"] is False
    assert "CLI token.json" in got["note"]


def test_revoke_failure_still_deletes_local(tokens, monkeypatch):
    """SSO 吊销失败（断网/凭据异常）也必须删掉本地 token。"""
    monkeypatch.setattr(esi, "revoke", lambda token: False)
    got = esi.forget(222)
    assert got["removed"] is True and got["revoked"] is False
    assert not (tokens / "222.json").exists()


def test_api_logout_contract(tokens):
    """接口契约：/api/logout 支持 all/cid，缺参数 400，响应带剩余角色。"""
    import webapp
    client = webapp.app.test_client()
    assert client.post("/api/logout", json={}).status_code == 400
    r = client.post("/api/logout", json={"cid": 111})
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    assert [x["id"] for x in body["removed"]] == [111]
    assert [c["id"] for c in body["characters"]] == [222]
    body = client.post("/api/logout", json={"all": True}).get_json()
    assert [x["id"] for x in body["removed"]] == [222]
    assert body["characters"] == [] and body["ok"] is True


def test_callback_returns_cid_in_redirect(tokens, monkeypatch):
    """授权回调必须带上 ?cid=<刚授权角色>：退出登录后重新授权才能选中正确角色（多账号不误选）。"""
    import oauth
    import webapp
    monkeypatch.setattr(webapp.appdb, "pop_oauth_state", lambda state: {"verifier": "v", "target": "fitting"})
    monkeypatch.setattr(oauth, "exchange_code", lambda code, verifier: {
        "id": 222, "name": "小号乙", "scopes": ["esi-skills.read_skills.v1"],
        "token": {"access_token": "a2", "refresh_token": "r2"}})
    r = webapp.app.test_client().get("/callback/?code=c&state=s")
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert "cid=222" in loc and loc.endswith("#/fitting")
    assert json.loads((tokens / "222.json").read_text())["name"] == "小号乙"
