"""
素材库 —— 工作台的持久化层（纯标准库 sqlite3）

四张表：
  articles   采集到的候选素材（标题/正文/来源/话题方向）
  analyses   结构分析结果（标题模式/选题类型/正文骨架）
  drafts     改写后的草稿（标题锁定 + 改写正文）
  settings   配置（LLM API、采集参数等）
"""

import os
import sqlite3
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "station.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    account      TEXT DEFAULT '',
    summary      TEXT DEFAULT '',
    body         TEXT DEFAULT '',
    body_len     INTEGER DEFAULT 0,
    topic        TEXT DEFAULT '',
    keyword      TEXT DEFAULT '',
    source       TEXT DEFAULT 'sogou-weixin',
    real_url     TEXT DEFAULT '',
    sogou_link   TEXT DEFAULT '',
    published_ts INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'candidate',
    created_at   TEXT DEFAULT '',
    UNIQUE(title, topic)
);

CREATE TABLE IF NOT EXISTS analyses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    title_pattern TEXT DEFAULT '',
    topic_type    TEXT DEFAULT '',
    hooks         TEXT DEFAULT '',
    skeleton      TEXT DEFAULT '',
    tags          TEXT DEFAULT '',
    created_at    TEXT DEFAULT '',
    FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS drafts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id    INTEGER,
    topic         TEXT DEFAULT '',
    title         TEXT DEFAULT '',
    body          TEXT DEFAULT '',
    outline       TEXT DEFAULT '',
    increments    TEXT DEFAULT '',
    source_urls   TEXT DEFAULT '',
    engine        TEXT DEFAULT '',
    status        TEXT DEFAULT 'draft',
    created_at    TEXT DEFAULT '',
    updated_at    TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_topic  ON articles(topic);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_analyses_art    ON analyses(article_id);
CREATE INDEX IF NOT EXISTS idx_drafts_art      ON drafts(article_id);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# 已存在的库做增量迁移（SQLite 不支持 ADD COLUMN IF NOT EXISTS）
MIGRATIONS = [
    ("articles", "sogou_link", "TEXT DEFAULT ''"),
    ("drafts", "wx_media_id", "TEXT DEFAULT ''"),
    ("drafts", "pushed_at", "TEXT DEFAULT ''"),
]


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    for table, col, decl in MIGRATIONS:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)]
        if col not in cols:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
    conn.commit()
    conn.close()


# ---------------- articles ----------------

def upsert_articles(items):
    """批量写入素材，按 (title, topic) 去重。返回新增条数。"""
    init()
    conn = connect()
    added = 0
    for it in items:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO articles
               (title, account, summary, body, body_len, topic, keyword,
                source, real_url, sogou_link, published_ts, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                title,
                it.get("real_account") or it.get("account") or "",
                it.get("summary") or "",
                it.get("body") or "",
                it.get("body_len") or len(it.get("body") or ""),
                it.get("topic") or "",
                it.get("keyword") or "",
                it.get("source") or "sogou-weixin",
                it.get("real_url") or "",
                it.get("sogou_link") or "",
                it.get("published_ts") or 0,
                it.get("status") or "candidate",
                now(),
            ),
        )
        if cur.rowcount:
            added += 1
    conn.commit()
    conn.close()
    return added


def list_articles(topic=None, status=None, has_body=None, limit=200, offset=0):
    conn = connect()
    sql = "SELECT * FROM articles WHERE 1=1"
    args = []
    if topic:
        sql += " AND topic = ?"
        args.append(topic)
    if status:
        sql += " AND status = ?"
        args.append(status)
    if has_body is True:
        sql += " AND body_len > 0"
    elif has_body is False:
        sql += " AND body_len = 0"
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    rows = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    return rows


def get_article(aid):
    conn = connect()
    r = conn.execute("SELECT * FROM articles WHERE id = ?", (aid,)).fetchone()
    conn.close()
    return dict(r) if r else None


def update_article_status(aid, status):
    conn = connect()
    conn.execute("UPDATE articles SET status = ? WHERE id = ?", (status, aid))
    conn.commit()
    conn.close()


def delete_article(aid):
    conn = connect()
    conn.execute("DELETE FROM articles WHERE id = ?", (aid,))
    conn.commit()
    conn.close()


def articles_need_body(limit=50, topic=None):
    """有搜狗链接、但还没有正文的素材 —— 用于第二轮补正文"""
    conn = connect()
    sql = ("SELECT * FROM articles WHERE body_len = 0 "
           "AND sogou_link IS NOT NULL AND sogou_link <> ''")
    args = []
    if topic:
        sql += " AND topic = ?"
        args.append(topic)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    rows = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    return rows


def update_article_body(aid, body="", real_url="", real_account="", real_title=""):
    conn = connect()
    fields, args = [], []
    if body:
        fields += ["body = ?", "body_len = ?"]
        args += [body, len(body)]
    if real_url:
        fields.append("real_url = ?")
        args.append(real_url)
    if real_account:
        fields.append("account = ?")
        args.append(real_account)
    if real_title:
        fields.append("title = ?")
        args.append(real_title)
    if not fields:
        conn.close()
        return
    args.append(aid)
    conn.execute("UPDATE articles SET %s WHERE id = ?" % ", ".join(fields), args)
    conn.commit()
    conn.close()


def topics_summary():
    """按话题统计素材数量"""
    conn = connect()
    rows = conn.execute(
        """SELECT topic,
                  COUNT(*)                       AS total,
                  SUM(CASE WHEN body_len>0 THEN 1 ELSE 0 END) AS with_body
           FROM articles GROUP BY topic ORDER BY total DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------- analyses ----------------

def save_analysis(article_id, data):
    init()
    conn = connect()
    conn.execute("DELETE FROM analyses WHERE article_id = ?", (article_id,))
    conn.execute(
        """INSERT INTO analyses
           (article_id, title_pattern, topic_type, hooks, skeleton, tags, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            article_id,
            data.get("title_pattern", ""),
            data.get("topic_type", ""),
            json.dumps(data.get("hooks", []), ensure_ascii=False),
            json.dumps(data.get("skeleton", []), ensure_ascii=False),
            json.dumps(data.get("tags", []), ensure_ascii=False),
            now(),
        ),
    )
    conn.commit()
    conn.close()


def get_analysis(article_id):
    conn = connect()
    r = conn.execute("SELECT * FROM analyses WHERE article_id = ?", (article_id,)).fetchone()
    conn.close()
    if not r:
        return None
    d = dict(r)
    for k in ("hooks", "skeleton", "tags"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    return d


def all_analyses():
    conn = connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM analyses")]
    conn.close()
    for d in rows:
        for k in ("hooks", "skeleton", "tags"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except Exception:
                d[k] = []
    return rows


# ---------------- drafts ----------------

def create_draft(data):
    init()
    conn = connect()
    t = now()
    cur = conn.execute(
        """INSERT INTO drafts
           (article_id, topic, title, body, outline, increments,
            source_urls, engine, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get("article_id"),
            data.get("topic", ""),
            data.get("title", ""),
            data.get("body", ""),
            json.dumps(data.get("outline", []), ensure_ascii=False)
            if isinstance(data.get("outline"), (list, dict)) else (data.get("outline") or ""),
            json.dumps(data.get("increments", []), ensure_ascii=False)
            if isinstance(data.get("increments"), (list, dict)) else (data.get("increments") or ""),
            json.dumps(data.get("source_urls", []), ensure_ascii=False)
            if isinstance(data.get("source_urls"), list) else (data.get("source_urls") or ""),
            data.get("engine", ""),
            data.get("status", "draft"),
            t, t,
        ),
    )
    conn.commit()
    did = cur.lastrowid
    conn.close()
    return did


def update_draft(did, **fields):
    if not fields:
        return
    conn = connect()
    keys = []
    args = []
    for k, v in fields.items():
        if isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False)
        keys.append("%s = ?" % k)
        args.append(v)
    keys.append("updated_at = ?")
    args.append(now())
    args.append(did)
    conn.execute("UPDATE drafts SET %s WHERE id = ?" % ", ".join(keys), args)
    conn.commit()
    conn.close()


def list_drafts(limit=200):
    conn = connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM drafts ORDER BY id DESC LIMIT ?", (limit,))]
    conn.close()
    for d in rows:
        for k in ("outline", "increments", "source_urls"):
            raw = d.get(k) or ""
            if raw.strip().startswith(("[", "{")):
                try:
                    d[k] = json.loads(raw)
                    continue
                except Exception:
                    pass
            d[k] = raw
    return rows


def get_draft(did):
    conn = connect()
    r = conn.execute("SELECT * FROM drafts WHERE id = ?", (did,)).fetchone()
    conn.close()
    if not r:
        return None
    d = dict(r)
    for k in ("outline", "increments", "source_urls"):
        raw = d.get(k) or ""
        if raw.strip().startswith(("[", "{")):
            try:
                d[k] = json.loads(raw)
                continue
            except Exception:
                pass
        d[k] = raw
    return d


def delete_draft(did):
    conn = connect()
    conn.execute("DELETE FROM drafts WHERE id = ?", (did,))
    conn.commit()
    conn.close()


# ---------------- settings ----------------

DEFAULT_SETTINGS = {
    "llm_base": "https://api.deepseek.com/v1",
    "llm_key": "",
    "llm_model": "deepseek-chat",
    "collect_delay": "25",
    "topics": "养老金,老年人感情",
    # ---- 微信公众号（草稿箱推送）----
    "wx_appid": "",
    "wx_appsecret": "",
    "wx_author": "",
    "wx_cover_media_id": "",
    # ---- 副号（科技马前卒）----
    "wx_appid2": "",
    "wx_appsecret2": "",
    "wx_author2": "",
    "wx_cover_media_id2": "",
    "wx_default_account": "1",
    "wx_source_url": "auto",       # auto=用素材原文链接 / none=留空
    "wx_need_comment": "0",
    "wx_only_fans": "0",
    "wx_cover_style": "preset",    # preset=本地生成封面 / custom=用自备封面
}


def get_setting(key, default=None):
    init()
    conn = connect()
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if r:
        return r["value"]
    return DEFAULT_SETTINGS.get(key, default)


def get_settings():
    init()
    conn = connect()
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    conn.close()
    out = dict(DEFAULT_SETTINGS)
    out.update(rows)
    return out


def set_setting(key, value):
    init()
    conn = connect()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def stats():
    init()
    conn = connect()
    a = conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
    ab = conn.execute("SELECT COUNT(*) c FROM articles WHERE body_len>0").fetchone()["c"]
    an = conn.execute("SELECT COUNT(*) c FROM analyses").fetchone()["c"]
    dr = conn.execute("SELECT COUNT(*) c FROM drafts").fetchone()["c"]
    conn.close()
    return {"articles": a, "articles_with_body": ab, "analyses": an, "drafts": dr}


if __name__ == "__main__":
    init()
    print("DB ready:", DB_PATH)
    print(json.dumps(stats(), ensure_ascii=False))
