"""ScrapePilot AI — SQLite storage.

Tables: sessions, pages, exports.
All queries are parameterized. API keys are never stored here.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

import config


def _connect():
    os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                settings_json TEXT NOT NULL,
                discovered_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                meta_title TEXT,
                meta_description TEXT,
                category TEXT,
                category_confidence REAL,
                category_reason TEXT,
                status_code INTEGER,
                scrape_status TEXT,
                error TEXT,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(session_id, url),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                format TEXT NOT NULL,
                kind TEXT NOT NULL,
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def create_session(session_id, url, settings):
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, url, status, started_at, settings_json)"
            " VALUES (?, ?, 'running', ?, ?)",
            (session_id, url, utcnow(), json.dumps(settings)),
        )


def update_session(session_id, **fields):
    allowed = {"status", "completed_at", "discovered_count",
               "success_count", "failed_count", "error"}
    sets, values = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            values.append(value)
    if not sets:
        return
    values.append(session_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", values
        )


def save_page(session_id, page):
    """page: dict from scraper/crawler. Upserts by (session_id, url)."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO pages
               (session_id, url, title, meta_title, meta_description,
                category, category_confidence, category_reason,
                status_code, scrape_status, error, data_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id, url) DO UPDATE SET
                 title=excluded.title, meta_title=excluded.meta_title,
                 meta_description=excluded.meta_description,
                 category=excluded.category,
                 category_confidence=excluded.category_confidence,
                 category_reason=excluded.category_reason,
                 status_code=excluded.status_code,
                 scrape_status=excluded.scrape_status,
                 error=excluded.error, data_json=excluded.data_json""",
            (
                session_id, page["url"], page.get("title"),
                page.get("meta_title"), page.get("meta_description"),
                page.get("category"), page.get("category_confidence"),
                page.get("category_reason"), page.get("status_code"),
                page.get("scrape_status"), page.get("error"),
                json.dumps(page.get("data", {})), utcnow(),
            ),
        )


def get_session(session_id):
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def list_sessions(limit=50):
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pages(session_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d["data_json"] or "{}")
            del d["data_json"]
            out.append(d)
        return out


def get_page(page_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pages WHERE id = ?", (page_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["data"] = json.loads(d["data_json"] or "{}")
        del d["data_json"]
        return d


def update_page_category(page_id, category):
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE pages SET category = ?, category_reason = ? WHERE id = ?",
            (category, "Corrected manually by the user.", page_id),
        )
        return cur.rowcount


def delete_page(page_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM pages WHERE id = ?", (page_id,))
        return cur.rowcount


def record_export(session_id, fmt, kind, filename):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO exports (session_id, format, kind, filename, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, fmt, kind, filename, utcnow()),
        )
