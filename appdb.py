"""应用 SQLite：本地装配存档 + OAuth 会话 state。"""

import json
import os
import secrets
import sqlite3
import time

import config


def connect():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(config.APP_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS local_fittings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, eft TEXT NOT NULL, ship_name TEXT NOT NULL DEFAULT '',
        created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS oauth_state(
        state TEXT PRIMARY KEY, verifier TEXT NOT NULL,
        created INTEGER NOT NULL, target TEXT NOT NULL);
    """)
    conn.commit()
    return conn


# ------------------------------------------------------------ 本地装配
def list_local_fittings():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id,name,ship_name,eft,created FROM local_fittings ORDER BY id DESC")
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_local_fitting(name, eft, ship_name):
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO local_fittings(name,eft,ship_name,created) VALUES(?,?,?,?)",
            (name, eft, ship_name, int(time.time())))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def delete_local_fitting(fid):
    conn = connect()
    try:
        conn.execute("DELETE FROM local_fittings WHERE id=?", (fid,))
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------ OAuth state
def new_oauth_state(target):
    """生成 Pending OAuth state（供 SSO 回调时换取 token）。"""
    state = "sim-" + secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    conn = connect()
    try:
        conn.execute("INSERT INTO oauth_state(state,verifier,created,target) "
                     "VALUES(?,?,?,?)",
                     (state, verifier, int(time.time()), target))
        conn.commit()
        return state, verifier
    finally:
        conn.close()


def pop_oauth_state(state):
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM oauth_state WHERE state=?",
                           (state,)).fetchone()
        if row:
            conn.execute("DELETE FROM oauth_state WHERE state=?", (state,))
            conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def oauth_state_lookup(state):
    """只读查询（回调判定用，不消耗）。"""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM oauth_state WHERE state=?", (state,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()