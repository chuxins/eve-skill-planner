"""应用配置：EVE 应用凭据 + 路径。"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
APP_DB = os.path.join(DATA_DIR, "app.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
LEGACY_DATA = os.path.expanduser("~/.eve-skill-planner")
TOKEN_DIR = os.path.join(LEGACY_DATA, "tokens")

# 本地凭据文件（gitignore）
_CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# 公网访问基址：OAuth 成功后回跳前端用（可用 EVE_SKILL_PLANNER_URL 覆盖）
PUBLIC_BASE = os.environ.get("EVE_SKILL_PLANNER_URL", "http://8.138.203.48:8090").rstrip("/")


def _file_config():
    """读取项目根目录 config.json（缺失/损坏时返回空 dict）。"""
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def eve_credentials():
    """返回 (client_id, client_secret, callback_url)。

    优先级：环境变量 → config.json（项目根目录）。
    三个字段各自独立回退，避免只设置部分环境变量时其余字段丢失。

    callback_url 必须与 EVE 应用后台登记的「回调地址(Callback URL)」逐字符一致，
    且该地址已由 nginx 反代到本应用（见 README「OAuth 接线」）。
    """
    cfg = _file_config()
    client_id = os.environ.get("EVE_CLIENT_ID") or cfg.get("client_id")
    client_secret = os.environ.get("EVE_CLIENT_SECRET") or cfg.get("client_secret")
    callback_url = os.environ.get("EVE_CALLBACK_URL") or cfg.get("callback_url")
    if not client_id or not client_secret:
        raise RuntimeError("EVE 应用凭据未配置（EVE_CLIENT_ID/EVE_CLIENT_SECRET 或 config.json）")
    if not callback_url:
        raise RuntimeError("EVE 回调地址未配置（EVE_CALLBACK_URL 或 config.json 的 callback_url）")
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