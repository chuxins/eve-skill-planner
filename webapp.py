"""eve-skill-planner Web 应用（Flask）。

- 静态前端：/（static/index.html，注入静态资源自动版本号）
- 模拟接口：/api/simulate、/api/eft/simulate、/api/search、/api/ships、/api/item/<tid>
- 弹药列表：/api/weapon/<tid>/charges（该武器全部兼容弹药，不限于货舱）
- 技能规划：/api/skillplan、/api/characters/<cid>/skillqueue
- ESI 接口：/api/characters、/api/characters/<cid>/fittings|skills|wallet|attributes
- OAuth：/api/auth/start → EVE SSO（本应用独立凭据 + PKCE）→ nginx 反代 /api/auth/callback → /callback/
- 本地装配存档：/api/local/fittings
"""

import argparse
import hashlib
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
from engine.data import StaticData, ammo_family
from engine.eft import parse_eft, render_eft
from engine.simulate import simulate, SimulationError
from engine.skillplan import build_plan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("webapp")

sde = StaticData()
app = Flask(__name__, static_folder=None)

# 物品详情里隐藏的纯功能性属性
_HIDDEN_ATTRS = set(range(182, 192)) | {277, 278, 279, 1286, 1287} | {280, 275, 276}


# ---------------------------------------------------------------- 静态
def _asset_version():
    """静态资源版本号：static/ 下所有文件 (相对路径, mtime, 大小) 的摘要。

    index.html 里用 {{ASSET_VERSION}} 占位，任何 JS/CSS/SVG 改动后版本号
    自动变化，不必再手工改 `app.js?v=NN`。
    """
    h = hashlib.md5()
    for root, _dirs, files in os.walk(config.STATIC_DIR):
        for fn in sorted(files):
            path = os.path.join(root, fn)
            try:
                st = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, config.STATIC_DIR)
            h.update(f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode("utf-8"))
    return h.hexdigest()[:10]


@app.route("/")
def index():
    with open(os.path.join(config.STATIC_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    resp = app.response_class(
        html.replace("{{ASSET_VERSION}}", _asset_version()), mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/favicon.ico")
def favicon_ico():
    """避免浏览器默认探测 /favicon.ico 产生 404 噪音；真实图标见 index.html 的 link。"""
    return "", 204


@app.route("/static/<path:name>")
def static_files(name):
    resp = send_from_directory(config.STATIC_DIR, name)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ---------------------------------------------------------------- 搜索
def _search_types(q, cats=None, slot=None, limit=50):
    q = q.strip().lower()
    out = []
    for tid, t in sde.types.items():
        if not t["published"]:
            continue
        if cats and t["category_id"] not in cats:
            continue
        name = t["name"].lower()
        en = t["name_en"].lower()
        if q and q not in name and not (q in en and (q.isascii() or len(q) >= 3)):
            continue
        s = sde.slot_of(tid)
        if slot and s != slot:
            continue
        attrs = sde.type_attrs.get(tid, {})
        out.append({"tid": tid, "name": t["name"], "name_en": t["name_en"],
                    "group_id": t["group_id"], "category_id": t["category_id"],
                    "group": sde.group_name(t["group_id"]),
                    "slot": s, "meta": t.get("meta_group_id"),
                    "family": ammo_family(sde.group_name(t["group_id"])),
                    "pg": attrs.get(30), "cpu": attrs.get(50)})
        if len(out) >= limit:
            break
    return out


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "")
    cats = request.args.get("cat")
    cat_ids = None
    if cats:
        cat_ids = set(int(x) for x in cats.split(",") if x.isdigit())
    slot = request.args.get("slot") or None
    limit = min(int(request.args.get("limit", 50)), 1000)
    return jsonify(_search_types(q, cat_ids, slot, limit))


# 逐门武器的可选弹药（SDE 全量兼容弹药，按武器 tid 缓存；SDE 运行期不变）
_weapon_charges_cache = {}


@app.route("/api/weapon/<int:tid>/charges")
def api_weapon_charges(tid):
    """该武器可装填的**全部**弹药（不限于装配/货舱里已有的），供弹药下拉框。

    匹配规则见 StaticData.charges_for：装填尺寸(attr 128) 一致 + 弹药组属于
    武器 chargeGroup1..5(attr 604-608)，且排除脚本/电容装料等无伤害「弹药」。
    """
    if tid not in _weapon_charges_cache:
        _weapon_charges_cache[tid] = sde.charges_for(tid)
    return jsonify(_weapon_charges_cache[tid])


@app.route("/api/ships")
def api_ships():
    group_id = request.args.get("group_id")
    rows = []
    for tid, t in sde.types.items():
        if t["category_id"] != 6 or not t["published"]:
            continue
        if group_id and t["group_id"] != int(group_id):
            continue
        rows.append({"tid": tid, "name": t["name"], "name_en": t["name_en"],
                     "group_id": t["group_id"],
                     "group": sde.group_name(t["group_id"]),
                     "race_id": t.get("race_id"), "race": sde.race_name(tid)})
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
    # charges: {武器 tid: 弹药 tid}，UI 中每门武器的显式弹药选择
    charges = {int(k): int(v) for k, v in (data.get("charges") or {}).items() if v}
    try:
        result = simulate(sde, ship_tid, items, skills, charges)
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


@app.post("/api/logout")
def api_logout():
    """退出登录：注销本地 token（all=true 全部，或只注销 body.cid）。

    尽力在 EVE SSO 侧吊销 refresh token；响应附带剩余已授权角色，便于前端
    一次刷新完成，不必再调 /api/characters。
    """
    data = request.get_json(silent=True) or {}
    cid = data.get("cid")
    if data.get("all"):
        results = esi.forget_all()
    elif cid:
        results = [esi.forget(int(cid))]
    else:
        return jsonify({"error": "需指定 cid 或 all=true"}), 400
    skipped = [r for r in results if not r["removed"]]
    log.info("logout: 已注销 %s，跳过 %s",
             [r["id"] for r in results if r["removed"]], [r["id"] for r in skipped])
    return jsonify({"ok": not skipped, "removed": results, "skipped": skipped,
                    "characters": esi.list_characters()})


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


@app.get("/api/characters/<int:cid>/attributes")
def api_char_attributes(cid):
    """角色有效属性（含植入体），训练时间估算用。"""
    try:
        return jsonify(esi.get_attributes(cid))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


def _scope_hint(exc, scope):
    """把 ESI 的 401/403 转成可读提示（提示重新授权缺的 scope）。"""
    msg = str(exc)
    if "401" in msg or "403" in msg:
        return f"缺少 {scope} 授权，请点页头「登录」重新授权"
    return msg


def _queue_row(sde, entry):
    """ESI 训练队列条目 → 展示用行（技能名从 SDE 补全）。"""
    tid = int(entry.get("skill_id") or 0)
    return {"position": int(entry.get("queue_position") or 0),
            "tid": tid, "name": sde.name(tid) if tid else "?",
            "finished_level": int(entry.get("finished_level") or 0),
            "start_date": entry.get("start_date"),
            "finish_date": entry.get("finish_date")}


@app.get("/api/characters/<int:cid>/skillqueue")
def api_char_skillqueue(cid):
    """训练队列；缺 read_skillqueue scope 时降级返回 error 字段（仍 200）。"""
    try:
        raw = esi.get_skillqueue(cid)
    except Exception as exc:
        return jsonify({"queue": [],
                        "error": _scope_hint(exc, "esi-skills.read_skillqueue.v1")})
    return jsonify({"queue": [_queue_row(sde, e) for e in raw], "error": None})


@app.post("/api/skillplan")
def api_skillplan():
    """技能计划：舰船 + 当前装配的需求技能、缺口与训练时间。

    body: {cid, ship_tid, items:[[tid,qty]], skills:{tid:level}}
    - 省略 skills → 后端直接向 ESI 拉取（权威）；提供则用请求值
    - attributes 始终取自 ESI（训练速率 = 主属性 + 副属性/2）
    - 训练队列缺 scope 只降级提示，不影响计划本身
    """
    data = request.get_json(force=True)
    cid = int(data.get("cid") or 0)
    ship_tid = int(data.get("ship_tid") or 0)
    items = [(int(a), int(b)) for a, b in data.get("items") or []]
    if not cid or not ship_tid:
        return jsonify({"error": "缺少角色或舰船"}), 400

    skills_source = "client"
    raw_skills = data.get("skills")
    if raw_skills is None:
        try:
            skills = esi.get_skills(cid)
            skills_source = "esi"
        except Exception as exc:
            return jsonify({"error": _scope_hint(exc, "esi-skills.read_skills.v1")}), 502
    else:
        skills = {int(k): int(v) for k, v in raw_skills.items()}

    attrs, attrs_error = {}, None
    try:
        attrs = esi.get_attributes(cid)
    except Exception as exc:
        attrs_error = _scope_hint(exc, "esi-skills.read_skills.v1")

    plan = build_plan(sde, ship_tid, [tid for tid, _ in items], skills, attrs)
    plan.update({"cid": cid, "skills_source": skills_source,
                 "attributes_error": attrs_error})
    try:
        plan["queue"] = [_queue_row(sde, e) for e in esi.get_skillqueue(cid)]
        plan["queue_error"] = None
    except Exception as exc:
        plan["queue"] = []
        plan["queue_error"] = _scope_hint(exc, "esi-skills.read_skillqueue.v1")
    return jsonify(plan)


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
    # 带上 cid：前端据此选中「刚授权的角色」，多账号时不会误选其它角色
    return redirect(f"{config.PUBLIC_BASE}/?ok=1&cid={char['id']}#/fitting")


def main():
    parser = argparse.ArgumentParser(description="eve-skill-planner Web")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()