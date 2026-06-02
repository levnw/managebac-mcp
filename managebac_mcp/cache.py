"""
Response cache — namespaced per user.

The cache key is (user_id, key). The user_id comes from the request context,
so a read for user A can NEVER return user B's row, even if both cached the
same logical key (e.g. "get_classes"). This is the isolation guarantee for
cached data.
"""
import json
import sqlite3
import time
from typing import Any

from .config import CACHE_DB
from .context import require_user

TTL = {
    "get_classes": 86400,        # 24h
    "get_timetable": 21600,      # 6h
    "get_tasks": 600,            # 10 min
    "get_task_detail": 1800,     # 30 min
    "get_files": 3600,           # 1h
    "get_journal": 1800,         # 30 min
    "get_units": 86400,          # 24h
    "get_file_content": 3600,    # 1h
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(CACHE_DB)
    # Migration: a pre-multi-user cache table has no user_id column. The cache
    # is disposable, so just drop and recreate it with the namespaced schema.
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cache'"
    ).fetchone()
    if existing:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(cache)").fetchall()]
        if "user_id" not in cols:
            conn.execute("DROP TABLE cache")
            conn.commit()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            user_id    TEXT NOT NULL,
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, key)
        )
    """)
    rl = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='request_log'"
    ).fetchone()
    if rl:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(request_log)").fetchall()]
        if "user_id" not in cols:
            conn.execute("DROP TABLE request_log")
            conn.commit()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS request_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          INTEGER NOT NULL,
            user_id     TEXT NOT NULL DEFAULT '',
            tool        TEXT NOT NULL,
            args        TEXT NOT NULL,
            response    TEXT NOT NULL,
            source      TEXT NOT NULL DEFAULT 'mcp',
            duration_ms INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def get(key: str) -> Any | None:
    uid = require_user().id
    with _connect() as conn:
        row = conn.execute(
            "SELECT value, expires_at FROM cache WHERE user_id = ? AND key = ?", (uid, key)
        ).fetchone()
    if row is None:
        return None
    value, expires_at = row
    if time.time() > expires_at:
        return None
    return json.loads(value)


def set(key: str, value: Any, ttl_key: str) -> None:
    uid = require_user().id
    ttl = TTL.get(ttl_key, 600)
    expires_at = int(time.time()) + ttl
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (user_id, key, value, expires_at) VALUES (?, ?, ?, ?)",
            (uid, key, json.dumps(value), expires_at),
        )


def invalidate(key: str) -> None:
    uid = require_user().id
    with _connect() as conn:
        conn.execute("DELETE FROM cache WHERE user_id = ? AND key = ?", (uid, key))


def clear_user() -> None:
    """Clear all cached data for the current user only."""
    uid = require_user().id
    with _connect() as conn:
        conn.execute("DELETE FROM cache WHERE user_id = ?", (uid,))


def log_request(tool: str, args: dict, response: Any, source: str = "mcp", duration_ms: int = 0) -> None:
    from .context import get_current_user
    user = get_current_user()
    uid = user.id if user else ""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO request_log (ts, user_id, tool, args, response, source, duration_ms) VALUES (?,?,?,?,?,?,?)",
            (int(time.time()), uid, tool, json.dumps(args), json.dumps(response), source, duration_ms),
        )
        conn.execute("DELETE FROM request_log WHERE id NOT IN (SELECT id FROM request_log ORDER BY id DESC LIMIT 500)")


def admin_activity(user_id: str | None = None, limit: int = 50) -> list[dict]:
    """Recent tool calls (admin view). Optionally filtered to one user.
    Does NOT include full responses — just what was called, when, how long."""
    with _connect() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT ts, user_id, tool, args, duration_ms FROM request_log "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ts, user_id, tool, args, duration_ms FROM request_log "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    out = []
    for r in rows:
        try:
            args = json.loads(r[3])
        except Exception:
            args = {}
        out.append({"ts": r[0], "user_id": r[1], "tool": r[2], "args": args, "duration_ms": r[4]})
    return out


def admin_user_stats(user_id: str) -> dict:
    """Request count + last-active timestamp for one user."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*), MAX(ts) FROM request_log WHERE user_id = ?", (user_id,)
        ).fetchone()
    return {"request_count": row[0] or 0, "last_active": row[1]}


def get_cache_entries() -> list[dict]:
    """All cache rows for the current user (for CLI inspection)."""
    uid = require_user().id
    with _connect() as conn:
        rows = conn.execute(
            "SELECT key, value, expires_at FROM cache WHERE user_id = ? ORDER BY key", (uid,)
        ).fetchall()
    now = int(time.time())
    return [
        {"key": r[0], "data": json.loads(r[1]),
         "expires_in_s": max(0, r[2] - now), "expired": r[2] < now}
        for r in rows
    ]
