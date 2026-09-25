"""Web 化 EVE SSO：发起授权（PKCE）+ 回调换 token + 角色校验。"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests

import config


def _pkce_pair():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _basic_auth(client_id, client_secret):
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.urlsafe_b64encode(raw).decode("ascii")


def authorize_url(state, verifier=None):
    """构造 EVE SSO 授权 URL（回调地址用已注册的 qq_auth_bot 8000 入口）。

    verifier 由调用方生成并随 state 存库；校验回调时用同一 verifier。
    """
    client_id, _, callback = config.eve_credentials()
    if verifier is None:
        verifier, _ = _pkce_pair()
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return config.SSO_AUTHORIZE + "?" + urlencode({
        "response_type": "code",
        "redirect_uri": callback,
        "client_id": client_id,
        "scope": " ".join(config.SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def exchange_code(code, verifier):
    """用授权码换 token 并校验角色 → {id, name, scopes, token}。"""
    client_id, client_secret, callback = config.eve_credentials()
    resp = requests.post(config.TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": verifier,
    }, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"换取 token 失败: {resp.status_code} {resp.text[:200]}")
    token = resp.json()
    verify = requests.get("https://login.eveonline.com/oauth/verify",
                          headers={"Authorization": f"Bearer {token['access_token']}"},
                          timeout=30)
    verify.raise_for_status()
    char = verify.json()
    return {
        "id": int(char["CharacterID"]),
        "name": char.get("CharacterName", str(char["CharacterID"])),
        "scopes": sorted(scp(token["access_token"])),
        "token": token,
    }


def scp(access_token):
    """从 access_token（JWT）解析 EVE 实际授予的 scope 列表。"""
    import json
    try:
        payload = str(access_token).split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return [str(x) for x in (claims.get("scp") or [])]
    except Exception:
        return []