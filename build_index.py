#!/usr/bin/env python3
"""构建本地 SDE 索引（SQLite）。

数据来源：EVE 官方 SDE（fuzzwork JSONL 格式）
    https://developers.eveonline.com/static-data/eve-online-static-data-latest-jsonl.zip
默认复用 /root/eve_esi/sde.zip（与钱包工具共用同一份）。

用法:
    python3 build_index.py                      # 复用本地 sde.zip
    python3 build_index.py --zip /path/to/sde.zip
    python3 build_index.py --force-download     # 重新下载 SDE
    python3 build_index.py --stats              # 只显示索引统计
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import zipfile

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SDE_URL = ("https://developers.eveonline.com/static-data/"
           "eve-online-static-data-latest-jsonl.zip")
DEFAULT_SDE_ZIP = "/root/eve_esi/sde.zip"
DB_PATH = os.path.join(BASE_DIR, "data", "staticdata.db")
BATCH = 5000

# SDE 中文名里存在「三钛 合金」这类汉字间多余空格（ESI 返回的写法没有空格）。
_CJK_SPACE_RE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])")


def clean_zh_name(name):
    return _CJK_SPACE_RE.sub("", str(name or "").replace("\u3000", " ")).strip()


def download_sde(path):
    print(f"下载 SDE（约 95MB）：{SDE_URL}")
    tmp = path + ".part"
    with requests.get(SDE_URL, headers={"User-Agent": "eve-skill-planner/1.0"},
                      stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    os.replace(tmp, path)
    print(f"已保存 {path}（{os.path.getsize(path) / 1048576:.1f} MB）")


def iter_jsonl(zf, name):
    with zf.open(name) as f:
        for raw in f:
            try:
                yield json.loads(raw)
            except ValueError:
                continue


def zh_of(names):
    names = names or {}
    return clean_zh_name(names.get("zh") or names.get("en") or "")


def create_schema(conn):
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS categories(
        category_id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS groups(
        group_id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL,
        name TEXT NOT NULL DEFAULT '', published INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS types(
        type_id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL DEFAULT 0,
        category_id INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '',
        name_en TEXT NOT NULL DEFAULT '', published INTEGER NOT NULL DEFAULT 0,
        volume REAL NOT NULL DEFAULT 0, capacity REAL NOT NULL DEFAULT 0,
        mass REAL NOT NULL DEFAULT 0, meta_group_id INTEGER,
        market_group_id INTEGER);
    CREATE TABLE IF NOT EXISTS attrs(
        attribute_id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
        display_name TEXT NOT NULL DEFAULT '', unit_id INTEGER,
        published INTEGER NOT NULL DEFAULT 0, high_is_good INTEGER NOT NULL DEFAULT 1,
        stackable INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS units(
        unit_id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
        display_name TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS effects(
        effect_id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
        effect_category INTEGER NOT NULL DEFAULT 0,
        discharge_attribute_id INTEGER, duration_attribute_id INTEGER,
        range_attribute_id INTEGER, is_offensive INTEGER NOT NULL DEFAULT 0,
        is_assistance INTEGER NOT NULL DEFAULT 0, modifier_info TEXT);
    CREATE TABLE IF NOT EXISTS type_attrs(
        type_id INTEGER NOT NULL, attribute_id INTEGER NOT NULL,
        value REAL NOT NULL, PRIMARY KEY(type_id, attribute_id));
    CREATE TABLE IF NOT EXISTS type_effects(
        type_id INTEGER NOT NULL, effect_id INTEGER NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(type_id, effect_id));
    CREATE TABLE IF NOT EXISTS type_bonuses(
        type_id INTEGER PRIMARY KEY, bonus_json TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_types_group ON types(group_id);
    CREATE INDEX IF NOT EXISTS idx_types_cat ON types(category_id);
    CREATE INDEX IF NOT EXISTS idx_groups_cat ON groups(category_id);
    """)


def rows_to_table(conn, table, cols, rows_iter, ncols):
    """按批次写入行；rows_iter 产出 (cols...) 元组。"""
    total = 0
    batch = []
    for row in rows_iter:
        if len(row) != ncols:
            continue
        batch.append(row)
        if len(batch) >= BATCH:
            conn.executemany(
                f"INSERT OR REPLACE INTO {table}({','.join(cols)}) "
                f"VALUES({','.join('?' * ncols)})", batch)
            total += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            f"INSERT OR REPLACE INTO {table}({','.join(cols)}) "
            f"VALUES({','.join('?' * ncols)})", batch)
        total += len(batch)
    return total


def build(conn, zip_path):
    started = time.time()
    counts = {}
    with zipfile.ZipFile(zip_path) as zf:
        counts["categories"] = rows_to_table(
            conn, "categories", ["category_id", "name"],
            ((int(c["_key"]), zh_of(c.get("name"))) for c in iter_jsonl(zf, "categories.jsonl")),
            2)
        print(f"  categories {counts['categories']}")

        counts["groups"] = rows_to_table(
            conn, "groups", ["group_id", "category_id", "name", "published"],
            ((int(g["_key"]), int(g.get("categoryID") or 0), zh_of(g.get("name")),
              int(bool(g.get("published")))) for g in iter_jsonl(zf, "groups.jsonl")),
            4)
        print(f"  groups {counts['groups']}")

        counts["types"] = rows_to_table(
            conn, "types",
            ["type_id", "group_id", "category_id", "name", "name_en",
             "published", "volume", "capacity", "mass", "meta_group_id",
             "market_group_id"],
            ((int(t["_key"]), int(t.get("groupID") or 0), 0,
              zh_of(t.get("name")), str((t.get("name") or {}).get("en") or ""),
              int(bool(t.get("published"))), float(t.get("volume") or 0),
              float(t.get("capacity") or 0), float(t.get("mass") or 0),
              t.get("metaGroupID"), t.get("marketGroupID"))
             for t in iter_jsonl(zf, "types.jsonl")),
            11)
        print(f"  types {counts['types']}")

        counts["attrs"] = rows_to_table(
            conn, "attrs",
            ["attribute_id", "name", "display_name", "unit_id", "published",
             "high_is_good", "stackable"],
            ((int(a["_key"]), str(a.get("name") or ""),
              str(a.get("displayName") or ""), a.get("unitID"),
              int(bool(a.get("published"))),
              int(bool(a.get("highIsGood") if a.get("highIsGood") is not None else True)),
              int(bool(a.get("stackable") if a.get("stackable") is not None else True)))
             for a in iter_jsonl(zf, "dogmaAttributes.jsonl")),
            7)
        print(f"  attrs {counts['attrs']}")

        counts["units"] = rows_to_table(
            conn, "units", ["unit_id", "name", "display_name"],
            ((int(u["_key"]), str(u.get("name") or ""),
              str(u.get("displayName") or "")) for u in iter_jsonl(zf, "dogmaUnits.jsonl")),
            3)
        print(f"  units {counts['units']}")

        counts["effects"] = rows_to_table(
            conn, "effects",
            ["effect_id", "name", "effect_category", "discharge_attribute_id",
             "duration_attribute_id", "range_attribute_id", "is_offensive",
             "is_assistance", "modifier_info"],
            ((int(e["_key"]), str(e.get("name") or ""),
              int(e.get("effectCategoryID") or 0), e.get("dischargeAttributeID"),
              e.get("durationAttributeID"), e.get("rangeAttributeID"),
              int(bool(e.get("isOffensive"))), int(bool(e.get("isAssistance"))),
              json.dumps(e.get("modifierInfo") or [], ensure_ascii=False))
             for e in iter_jsonl(zf, "dogmaEffects.jsonl")),
            9)
        print(f"  effects {counts['effects']}")

        # 只索引已发布类型的属性/效果（非发布类型不会出现在装配中）
        pub = set(r[0] for r in conn.execute("SELECT type_id FROM types WHERE published=1"))
        counts["type_attrs"] = rows_to_table(
            conn, "type_attrs", ["type_id", "attribute_id", "value"],
            ((int(t["_key"]), int(a["attributeID"]), float(a["value"]))
             for t in iter_jsonl(zf, "typeDogma.jsonl") if int(t["_key"]) in pub
             for a in t.get("dogmaAttributes") or []),
            3)
        print(f"  type_attrs {counts['type_attrs']}")

        counts["type_effects"] = rows_to_table(
            conn, "type_effects", ["type_id", "effect_id", "is_default"],
            ((int(t["_key"]), int(e["effectID"]), int(bool(e.get("isDefault"))))
             for t in iter_jsonl(zf, "typeDogma.jsonl") if int(t["_key"]) in pub
             for e in t.get("dogmaEffects") or []),
            3)
        print(f"  type_effects {counts['type_effects']}")

        counts["type_bonuses"] = rows_to_table(
            conn, "type_bonuses", ["type_id", "bonus_json"],
            ((int(b["_key"]), json.dumps(b, ensure_ascii=False))
             for b in iter_jsonl(zf, "typeBonus.jsonl")),
            2)
        print(f"  type_bonuses {counts['type_bonuses']}")

        # 回填 types.category_id（由 groups 连带）
        conn.execute("UPDATE types SET category_id=(SELECT g.category_id FROM groups g "
                     "WHERE g.group_id=types.group_id)")
        conn.commit()
    print(f"✅ 索引完成，耗时 {time.time() - started:.1f}s")
    return counts


def stats(conn):
    n_ships = conn.execute("SELECT COUNT(*) FROM types WHERE published=1 AND category_id=6").fetchone()[0]
    n_mods = conn.execute("SELECT COUNT(*) FROM types WHERE published=1 AND category_id=7").fetchone()[0]
    n_charge = conn.execute("SELECT COUNT(*) FROM types WHERE published=1 AND category_id=8").fetchone()[0]
    n_drone = conn.execute("SELECT COUNT(*) FROM types WHERE published=1 AND category_id=18").fetchone()[0]
    n_skill = conn.execute("SELECT COUNT(*) FROM types WHERE published=1 AND category_id=16").fetchone()[0]
    n_pub = conn.execute("SELECT COUNT(*) FROM types WHERE published=1").fetchone()[0]
    n_attrs = conn.execute("SELECT COUNT(*) FROM type_attrs").fetchone()[0]
    print(f"已发布类型 {n_pub}：舰船 {n_ships} / 模块 {n_mods} / 弹药 {n_charge} /"
          f" 无人机 {n_drone} / 技能 {n_skill}")
    print(f"类型属性行 {n_attrs}")


def main():
    parser = argparse.ArgumentParser(description="构建本地 SDE 索引")
    parser.add_argument("--zip", default=None, help="SDE zip 路径（默认 %(default)s 可用时）")
    parser.add_argument("--force-download", action="store_true", help="强制重新下载 SDE")
    parser.add_argument("--stats", action="store_true", help="只显示索引统计")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    create_schema(conn)

    if args.stats:
        stats(conn)
        return

    zip_path = args.zip or (DEFAULT_SDE_ZIP if os.path.exists(DEFAULT_SDE_ZIP) else None)
    if args.force_download or not zip_path or not os.path.exists(zip_path):
        zip_path = download_sde(SDE_URL.split("/")[-1])
    else:
        print(f"复用本地 SDE：{zip_path}")

    build(conn, zip_path)
    stats(conn)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        sys.exit(1)