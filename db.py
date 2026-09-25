"""SQLite 本地库：用户、会话、邀请码、文章、素材（文章/素材按用户隔离）。"""
import secrets
import sqlite3
import time

import config


def conn():
    config.ensure_dirs()
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            settings_enc TEXT DEFAULT '',
            invite_code TEXT DEFAULT '',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS invite_codes (
            code TEXT PRIMARY KEY,
            used INTEGER DEFAULT 0,
            used_by TEXT DEFAULT '',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT DEFAULT '',
            title TEXT DEFAULT '',
            content_md TEXT DEFAULT '',
            content_html TEXT DEFAULT '',
            cover TEXT DEFAULT '',
            theme TEXT DEFAULT 'default',
            status TEXT DEFAULT 'draft',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT DEFAULT '',
            path TEXT DEFAULT '',
            size INTEGER DEFAULT 0,
            created_at TEXT
        );
        """)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


# ---------------- 用户 ----------------
def create_user(username, password_salt, password_hash, invite_code=""):
    with conn() as c:
        c.execute(
            "INSERT INTO users(username,password_salt,password_hash,invite_code,created_at) VALUES(?,?,?,?,?)",
            (username, password_salt, password_hash, invite_code, _now()),
        )
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_user_by_username(username):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def get_user(user_id):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def update_user_settings(user_id, settings_enc):
    with conn() as c:
        c.execute("UPDATE users SET settings_enc=? WHERE id=?", (settings_enc, user_id))


# ---------------- 会话 ----------------
def create_session(user_id):
    token = secrets.token_hex(32)
    with conn() as c:
        c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, user_id, _now()))
    return token


def get_user_id_by_token(token):
    with conn() as c:
        row = c.execute("SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
        return row["user_id"] if row else None


def delete_session(token):
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


# ---------------- 邀请码 ----------------
def add_invite_code(code):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO invite_codes(code,used,created_at) VALUES(?,0,?)", (code, _now()))


def list_invite_codes():
    with conn() as c:
        return c.execute("SELECT * FROM invite_codes ORDER BY code").fetchall()


def use_invite_code(code, username):
    with conn() as c:
        row = c.execute("SELECT * FROM invite_codes WHERE code=?", (code,)).fetchone()
        if not row or row["used"]:
            return False
        c.execute("UPDATE invite_codes SET used=1, used_by=? WHERE code=?", (username, code))
        return True


# ---------------- 文章（按用户隔离） ----------------
def list_articles(user_id):
    with conn() as c:
        return c.execute("SELECT * FROM articles WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()


def insert_article(user_id, topic, title, content_md, content_html, cover, theme):
    with conn() as c:
        c.execute(
            "INSERT INTO articles(user_id,topic,title,content_md,content_html,cover,theme,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user_id, topic, title, content_md, content_html, cover, theme, "draft", _now(), _now()),
        )
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_article(user_id, article_id):
    with conn() as c:
        return c.execute("SELECT * FROM articles WHERE id=? AND user_id=?", (article_id, user_id)).fetchone()


def update_article(user_id, article_id, **fields):
    allowed = {"topic", "title", "content_md", "content_html", "cover", "theme", "status"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    sets.append("updated_at=?")
    vals.append(_now())
    vals.extend([article_id, user_id])
    with conn() as c:
        c.execute(f"UPDATE articles SET {','.join(sets)} WHERE id=? AND user_id=?", vals)


def delete_article(user_id, article_id):
    with conn() as c:
        c.execute("DELETE FROM articles WHERE id=? AND user_id=?", (article_id, user_id))


# ---------------- 素材（按用户隔离） ----------------
def list_materials(user_id):
    with conn() as c:
        return c.execute("SELECT * FROM materials WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()


def insert_material(user_id, name, path, size):
    with conn() as c:
        c.execute(
            "INSERT INTO materials(user_id,name,path,size,created_at) VALUES(?,?,?,?,?)",
            (user_id, name, path, size, _now()),
        )
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_material(user_id, material_id):
    with conn() as c:
        return c.execute("SELECT * FROM materials WHERE id=? AND user_id=?", (material_id, user_id)).fetchone()


def delete_material(user_id, material_id):
    with conn() as c:
        c.execute("DELETE FROM materials WHERE id=? AND user_id=?", (material_id, user_id))
