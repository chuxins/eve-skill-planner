"""应用配置：EVE 应用凭据（复用 eve_esi 的 EVE developer 应用）+ 路径。"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
APP_DB = os.path.join(DATA_DIR, "app.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
LEGACY_DATA = os.path.expanduser("~/.eve-skill-planner")
TOKEN_DIR = os.path.join(LEGACY_DATA, "tokens")

# EVE 应用凭据来源：eve_esi/config.json（可用环境变量覆盖）
_EVE_ESI_CONFIG = "/root/eve_esi/config.json"


def eve_credentials():
    """返回 (client_id, client_secret, callback_url)。"""
    client_id = os.environ.get("EVE_CLIENT_ID")
    client_secret = os.environ.get("EVE_CLIENT_SECRET")
    callback_url = os.environ.get("EVE_CALLBACK_URL")
    if not client_id and os.path.exists(_EVE_ESI_CONFIG):
        try:
            cfg = json.load(open(_EVE_ESI_CONFIG))
        except (OSError, ValueError):
            cfg = {}
        client_id = client_id or cfg.get("client_id")
        client_secret = client_secret or cfg.get("client_secret")
        callback_url = callback_url or cfg.get("callback_url")
    if not client_id or not client_secret:
        raise RuntimeError("EVE 应用凭据未配置（EVE_CLIENT_ID/EVE_CLIENT_SECRET）")
    return client_id, client_secret, callback_url


# 授权范围：模拟装配所需
SCOPES = [
    "esi-fittings.read_fittings.v1",
    "esi-fittings.write_fittings.v1",
    "esi-skills.read_skills.v1",
    "esi-wallet.read_character_wallet.v1",
]

PORT = 8090
SSO_AUTHORIZE = "https://login.eveonline.com/v2/oauth/authorize"
TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
ESI_BASE = "https://esi.evetech.net"