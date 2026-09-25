"""eve-skill-planner Web 应用（Flask）。

- 静态前端：/（static/index.html）
- 模拟接口：/api/simulate、/api/eft/simulate、/api/search、/api/ships、/api/item/<tid>
- ESI 接口：/api/characters、/api/characters/<cid>/fittings|skills|wallet
- OAuth：/api/auth/start → EVE SSO → qq_auth_bot 转发 → /callback/
- 本地装配存档：/api/local/fittings
"""

import argparse
import json
import logging
import os
import re
from urllib.parse import parse_qs, urlparse

from flask import Flask, jsonify, redirect, request, send_from_directory

import appdb
import config
import esi
import oauth
from engine.data import StaticData
from engine.eft import parse_eft, render_eft
from engine.simulate import simulate, SimulationError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("webapp")

sde = StaticData()
app = Flask(__name__, static_folder=None)

# 物品详情里隐藏的纯功能性属性
_HIDDEN_ATTRS = set(range(182, 192)) | {277, 278, 279, 1286, 1287} | {280, 275, 276}


# ---------------------------------------------------------------- 静态
@app.route("/")
def index():
    resp = send_from_directory(config.STATIC_DIR, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/static/<path:name>")
def static_files(name):
    resp = send_from_directory(config.STATIC_DIR, name)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ---------------------------------------------------------------- 搜索
def _search_types(q, cats=None, limit=50):
    q = q.strip().lower()
    out = []
    for tid, t in sde.types.items():
        if not t["published"]:
            continue
        if cats and t["category_id"] not in cats:
            continue
        name = t["name"].lower()
        en = t["name_en"].lower()
        if q in name or (q in en and (q.isascii() or len(q) >= 3)):
            out.append({"tid": tid, "name": t["name"], "name_en": t["name_en"],
                        "group_id": t["group_id"], "category_id": t["category_id"],
                        "group": sde.group_name(t["group_id"])})
            if len(out) >= limit:
                break
    return out


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "")
    if not q:
        return jsonify([])
    cats = request.args.get("cat")
    cat_ids = None
    if cats:
        cat_ids = set(int(x) for x in cats.split(",") if x.isdigit())
    limit = min(int(request.args.get("limit", 50)), 100)
    return jsonify(_search_types(q, cat_ids, limit))


@app.route("/api/ships")
def api_ships():
    group_id = request.args.get("group_id")
    rows = []
    for tid, t in sde.types.items():
        if t["category_id"] != 6 or not t["published"]:
            continue
        if group_id and t["group_id"] != int(group_id):
            continue
        rows.append({"tid": tid, "name": t["name"], "group_id": t["group_id"],
                     "group": sde.group_name(t["group_id"])})
    rows.sort(key=lambda x: (x["group_id"], x["name"]))
    return jsonify(rows)


@app.route("/api/groups")
def api_groups():
    """舰船分组（按 category 6 的 groups，供左栏树）。"""
    seen = {}
    for gid, g in sde.groups.items():
        if g["category_id"] == 6:
            seen[gid] = g["name"]
    seen = sorted(seen.items(), key=lambda kv: kv[1])
    # 按舰船数量过滤空组
    return jsonify([{"group_id": gid, "name": name} for gid, name in seen])


# ---------------------------------------------------------------- 物品详情
@app.route("/api/item/<int:tid>")
def api_item(tid):
    t = sde.types.get(tid)
    if not t:
        return jsonify({"error": "not found"}), 404
    attrs = []
    for aid, val in sde.type_attrs.get(tid, {}).items():
        if aid in _HIDDEN_ATTRS or not val:
            continue
        meta = sde.attrs.get(aid)
        if not meta or not meta["display_name"]:
            continue
        attrs.append({"id": aid, "name": meta["display_name"],
                      "value": val, "unit": sde.units.get(meta["unit_id"], {}).get("display_name", "")})
    attrs.sort(key=lambda x: x["id"])

    req_skills = []
    ta = sde.type_attrs.get(tid, {})
    for i in range(5):
        sk = ta.get((182, 183, 184, 185, 186)[i])
        lv = ta.get((277, 278, 279, 1286, 1287)[i])
        if sk:
            req_skills.append({"tid": int(sk), "name": sde.name(int(sk)), "level": int(lv or 0)})

    traits = []
    if t["category_id"] == 6 and tid in sde.traits:
        traits = _format_traits(sde.traits[tid])

    return jsonify({
        "tid": tid, "name": t["name"], "name_en": t["name_en"],
        "group": sde.group_name(t["group_id"]),
        "category_id": t["category_id"],
        "attrs": attrs, "required_skills": req_skills, "traits": traits,
    })


def _strip_showinfo(text):
    """剥掉 <a href=showinfo:...>…</a> 标签。"""
    out = re.sub(r"<a href=['\"]?showinfo:\d+['\"]?>", "", text or "")
    out = re.sub(r"</a>", "", out)
    out = re.sub(r"<br\s*/?>", "\n", out)
    return out


def _format_traits(tb):
    out = []
    for b in tb.get("roleBonuses") or []:
        txt = _strip_showinfo((b.get("bonusText") or {}).get("zh") or
                              (b.get("bonusText") or {}).get("en"))
        out.append({"kind": "role", "text": txt, "bonus": b.get("bonus")})
    for entry in tb.get("types") or []:
        sk_tid = entry.get("_key")
        sk_name = sde.name(int(sk_tid)) if sk_tid else ""
        for b in entry.get("_value") or []:
            txt = _strip_showinfo((b.get("bonusText") or {}).get("zh") or
                                  (b.get("bonusText") or {}).get("en"))
            out.append({"kind": "skill", "skill": sk_name, "skill_tid": int(sk_tid),
                        "text": txt, "bonus": b.get("bonus")})
    return out


# ---------------------------------------------------------------- 模拟
@app.post("/api/simulate")
def api_simulate():
    data = request.get_json(force=True)
    ship_tid = int(data.get("ship_tid") or 0)
    items = [(int(a), int(b)) for a, b in data.get("items") or []]
    skills = {int(k): int(v) for k, v in (data.get("skills") or {}).items()}
    try:
        result = simulate(sde, ship_tid, items, skills)
    except SimulationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_decorate(result))


@app.post("/api/eft/simulate")
def api_eft_simulate():
    data = request.get_json(force=True)
    ship, fit_name, items = parse_eft(data.get("eft") or "")
    skills = {int(k): int(v) for k, v in (data.get("skills") or {}).items()}
    if not ship:
        return jsonify({"error": "无法解析 EFT"}), 400
    ship_tid = _resolve_type(ship)
    if not ship_tid:
        return jsonify({"error": f"找不到舰船：{ship}"}), 400
    resolved = []
    unknown = []
    for name, qty in items:
        tid = _resolve_type(name)
        if tid:
            resolved.append((tid, qty))
        else:
            unknown.append(name)
    try:
        result = simulate(sde, ship_tid, resolved, skills)
    except SimulationError as exc:
        return jsonify({"error": str(exc)}), 400
    result["fit_name"] = fit_name
    result["unknowns"] = unknown
    return jsonify(_decorate(result))


def _resolve_type(name):
    """按中文名/英文名精确匹配 typeID。"""
    n = name.strip()
    for tid, t in sde.types.items():
        if t["published"] and (t["name"] == n or t["name_en"] == n):
            return tid
    return None


def _decorate(result):
    """补充展示字段（图标名等）。"""
    for item in result.get("items", []):
        item["icon"] = f"https://images.evetech.net/types/{item['tid']}/icon?size=32"
    return result


# ---------------------------------------------------------------- 角色 / ESI
@app.route("/api/characters")
def api_characters():
    return jsonify(esi.list_characters())


@app.get("/api/characters/<int:cid>/skills")
def api_char_skills(cid):
    try:
        return jsonify(esi.get_skills(cid))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/characters/<int:cid>/wallet")
def api_char_wallet(cid):
    try:
        return jsonify({"balance": esi.get_wallet(cid)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/characters/<int:cid>/fittings")
def api_char_fittings(cid):
    try:
        data = esi.get_fittings(cid)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    out = []
    for f in data:
        items = []
        for it in f.get("items") or []:
            tid = int(it.get("type_id") or 0)
            items.append({"tid": tid, "qty": int(it.get("quantity") or 0),
                          "flag": it.get("flag", ""),
                          "name": sde.name(tid) if tid else "?"})
        out.append({"fitting_id": f["fitting_id"], "name": f["name"],
                    "ship_tid": int(f.get("ship_type_id") or 0),
                    "ship": sde.name(int(f.get("ship_type_id") or 0)),
                    "items": items})
    return jsonify(out)


@app.post("/api/characters/<int:cid>/fittings/save")
def api_char_fittings_save(cid):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    items = data.get("items") or []
    ship_tid = int(data.get("ship_tid") or 0)
    if not name or not ship_tid:
        return jsonify({"error": "缺少装配名或舰船"}), 400
    try:
        status, body = esi.create_fitting(
            cid, name, "from eve-skill-planner",
            [{"type_id": t, "quantity": q, "flag": f} for t, q, f in items], ship_tid)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    if status >= 300:
        return jsonify({"error": f"ESI 拒绝：{status} {body}"}), 502
    return jsonify({"ok": True, "body": body})


# ---------------------------------------------------------------- 本地装配
@app.get("/api/local/fittings")
def api_local_fittings():
    return jsonify(appdb.list_local_fittings())


@app.post("/api/local/fittings")
def api_local_fittings_save():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    eft = data.get("eft") or ""
    if not name or not eft:
        return jsonify({"error": "缺少名称或 EFT"}), 400
    ship_name = data.get("ship_name", "")
    return jsonify({"id": appdb.save_local_fitting(name, eft, ship_name)})


@app.delete("/api/local/fittings/<int:fid>")
def api_local_fittings_delete(fid):
    appdb.delete_local_fitting(fid)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- OAuth
@app.get("/api/auth/start")
def api_auth_start():
    target = request.args.get("target") or "fitting"
    state, verifier = appdb.new_oauth_state(target)
    return redirect(oauth.authorize_url(state, verifier))


@app.get("/callback/")
def api_callback():
    qs = parse_qs(urlparse(request.url).query)
    code = (qs.get("code") or [None])[0]
    state = (qs.get("state") or [None])[0]
    error = (qs.get("error") or [None])[0]
    if error:
        return f"<h2>授权失败：{error}</h2>", 400
    if not code or not state:
        return "<h2>缺少授权码</h2>", 400
    entry = appdb.pop_oauth_state(state)
    if not entry:
        return "<h2>state 无效或已过期</h2>", 400
    try:
        char = oauth.exchange_code(code, entry["verifier"])
    except Exception as exc:
        return f"<h2>换取 token 失败：{exc}</h2>", 502
    # 保存到 tokens/<cid>.json（既有格式）
    os.makedirs(config.TOKEN_DIR, exist_ok=True)
    token = {
        "id": char["id"], "name": char["name"],
        "scopes": char["scopes"],
        "access_token": char["token"]["access_token"],
        "refresh_token": char["token"].get("refresh_token", ""),
        "expires": 0,
    }
    with open(os.path.join(config.TOKEN_DIR, f"{char['id']}.json"), "w") as f:
        json.dump(token, f)
    log.info("已授权角色：%s (ID:%d)，scopes=%s", char["name"], char["id"], char["scopes"])
    return redirect("/#/fitting?ok=1")


def main():
    parser = argparse.ArgumentParser(description="eve-skill-planner Web")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()