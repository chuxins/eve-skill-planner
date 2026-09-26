"""ESI 客户端：读取既有角色 token（~/.eve-skill-planner/tokens/<cid>.json），
过期自动刷新；提供装配/技能/钱包接口。"""

import base64
import json
import os
import threading
import time

import requests

import config

_lock = threading.Lock()
_cache = {}          # cid -> (token_dict, load_ts)
TOKEN_TTL = 1200     # 秒，< 20 分钟有效期


def _granted_scopes(access_token):
    """从 access_token（JWT）解析 EVE 实际授予的 scope。"""
    try:
        payload = str(access_token).split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return set(claims.get("scp") or [])
    except Exception:
        return set()


def _load_token_file(cid):
    """读取 tokens/<cid>.json（旧 Web 格式 {id,name,scopes,...}）。"""
    path = os.path.join(config.TOKEN_DIR, f"{cid}.json")
    if not os.path.exists(path):
        # 回退 CLI 格式 token.json
        alt = os.path.join(config.LEGACY_DATA, "token.json")
        if os.path.exists(alt):
            d = json.load(open(alt))
            if str(d.get("CharacterID")) == str(cid):
                return {
                    "id": cid,
                    "name": d.get("CharacterName", str(cid)),
                    "access_token": d.get("access_token"),
                    "refresh_token": d.get("refresh_token"),
                }
        return None
    return json.load(open(path))


def _verify_name(token):
    """从 access_token 拉取角色名（缓存于 token dict）。"""
    try:
        resp = requests.get("https://login.eveonline.com/oauth/verify",
                            headers={"Authorization": f"Bearer {token['access_token']}"},
                            timeout=15)
        if resp.ok:
            return resp.json().get("CharacterName")
    except requests.RequestException:
        pass
    return None


def list_characters():
    """已授权角色列表（从 token 文件推断，无敏感字段）。"""
    out = []
    if not os.path.isdir(config.TOKEN_DIR):
        return out
    for fn in sorted(os.listdir(config.TOKEN_DIR)):
        if not fn.endswith(".json"):
            continue
        cid = fn[:-5]
        if not cid.isdigit():
            continue
        d = _load_token_file(cid)
        if not d:
            continue
        name = d.get("name") or d.get("CharacterName")
        if not name:
            try:
                name = _verify_name(get_token(int(cid))) or cid
            except Exception:
                name = cid
        out.append({
            "id": int(cid),
            "name": name,
            "scopes": sorted(_granted_scopes(d.get("access_token", ""))),
        })
    return out


def _refresh(cid, token):
    _, secret, _ = config.eve_credentials()
    resp = requests.post(config.TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
        "client_id": config.eve_credentials()[0],
        "client_secret": secret,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    token["access_token"] = data["access_token"]
    if data.get("refresh_token"):
        token["refresh_token"] = data["refresh_token"]
    token["expires"] = time.time() + data.get("expires_in", 1200)
    # 回写（保持既有键结构，追加 access/refresh/expires）
    path = os.path.join(config.TOKEN_DIR, f"{cid}.json")
    if os.path.exists(path):
        try:
            json.dump(token, open(path, "w"))
        except OSError:
            pass
    return token


def get_token(cid):
    """取可用 access_token（必要时刷新）。"""
    cid = int(cid)
    with _lock:
        hit, ts = _cache.get(cid, (None, 0))
        if hit and time.time() - ts < TOKEN_TTL:
            if time.time() < hit.get("expires", 0) - 60:
                return hit
        token = _load_token_file(cid)
        if not token or not token.get("refresh_token"):
            raise RuntimeError(f"角色 {cid} 无可用 token")
        if time.time() >= token.get("expires", 0) - 60:
            token = _refresh(cid, token)
        _cache[cid] = (token, time.time())
        return token


def revoke(token):
    """在 EVE SSO 侧吊销 refresh token（RFC 7009）。

    网络/凭据异常一律返回 False（本地 token 仍会被删除，只是 SSO 侧未失效）。
    """
    rt = (token or {}).get("refresh_token") or (token or {}).get("access_token")
    if not rt:
        return False
    try:
        client_id, secret, _ = config.eve_credentials()
        resp = requests.post(config.SSO_REVOKE, data={
            "token_type_hint": "refresh_token",
            "token": rt,
            "client_id": client_id,
            "client_secret": secret,
        }, timeout=15)
        return resp.ok
    except Exception:
        return False


def forget(cid):
    """退出登录（单个角色）：删本地 token 文件 + 清内存缓存，尽力吊销 SSO 令牌。

    返回 {id,name,removed,revoked,note}。CLI 的 token.json 不属于本应用，
    绝不删除；此类角色 removed=False 并通过 note 提示手动处理。
    """
    cid = int(cid)
    path = os.path.join(config.TOKEN_DIR, f"{cid}.json")
    with _lock:
        token, _ = _cache.pop(cid, (None, 0))
    if not token:
        token = _load_token_file(cid)
        if token and str(token.get("id", cid)) != str(cid) and not os.path.exists(path):
            token = None
    name = (token or {}).get("name") or (token or {}).get("CharacterName") or str(cid)
    revoked = revoke(token) if token else False
    removed = False
    note = "仅存在于 CLI token.json（~/.eve-skill-planner/token.json），需手动删除"
    if os.path.exists(path):
        try:
            os.remove(path)
            removed, note = True, None
        except OSError as exc:
            note = f"删除失败：{exc}"
    return {"id": cid, "name": name, "removed": removed, "revoked": revoked, "note": note}


def forget_all():
    """退出登录（全部角色）：清空 tokens/ 并清内存缓存。"""
    out = []
    if os.path.isdir(config.TOKEN_DIR):
        for fn in sorted(os.listdir(config.TOKEN_DIR)):
            if fn.endswith(".json") and fn[:-5].isdigit():
                out.append(forget(int(fn[:-5])))
    with _lock:
        _cache.clear()
    return out


def _headers(cid):
    return {"Authorization": f"Bearer {get_token(cid)['access_token']}",
            "User-Agent": "eve-skill-planner/1.0 (your-contact@example.com)"}


def esi_get(cid, path, params=None):
    url = f"{config.ESI_BASE}{path}"
    resp = requests.get(url, headers=_headers(cid), params=params, timeout=30)
    if resp.status_code == 502:          # ESI 偶发服务端故障 → 重试一次
        time.sleep(1)
        resp = requests.get(url, headers=_headers(cid), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_fittings(cid):
    """角色已保存装配列表。"""
    return esi_get(cid, f"/latest/characters/{cid}/fittings/?datasource=tranquility")


def get_skills(cid):
    """角色技能等级 {skill_type_id: 活跃等级}。"""
    data = esi_get(cid, f"/latest/characters/{cid}/skills/?datasource=tranquility")
    return {int(s["skill_id"]): int(s.get("active_skill_level") or 0)
            for s in data.get("skills", [])}


def get_attributes(cid):
    """角色有效属性（含植入体）：{perception: n, ...}。

    实测 ESI 该接口返回扁平整数（与 swagger 文档的 base/implant 对象不同），
    两种形状都兼容，便于后续改版。
    """
    data = esi_get(cid, f"/latest/characters/{cid}/attributes/?datasource=tranquility")
    out = {}
    for key in ("charisma", "intelligence", "memory", "perception", "willpower"):
        val = data.get(key)
        if isinstance(val, dict):
            out[key] = float(val.get("base") or 0) + float(val.get("implant") or 0)
        elif isinstance(val, (int, float)):
            out[key] = float(val)
    return out


def get_skillqueue(cid):
    """角色训练队列（需 esi-skills.read_skillqueue.v1）。"""
    return esi_get(cid, f"/latest/characters/{cid}/skillqueue/?datasource=tranquility")


def get_wallet(cid):
    return esi_get(cid, f"/latest/characters/{cid}/wallet/?datasource=tranquility")


def create_fitting(cid, name, description, items, ship_type_id):
    """写回 ESI（需 esi-fittings.write_fittings.v1）。"""
    _, secret, _ = config.eve_credentials()
    url = f"{config.ESI_BASE}/latest/characters/{cid}/fittings/?datasource=tranquility"
    payload = {
        "name": name, "description": description,
        "items": items, "ship_type_id": int(ship_type_id),
    }
    resp = requests.post(url, headers=_headers(cid), json=payload, timeout=30)
    if resp.status_code == 502:
        time.sleep(1)
        resp = requests.post(url, headers=_headers(cid), json=payload, timeout=30)
    return resp.status_code, resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text