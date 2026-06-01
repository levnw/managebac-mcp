import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .config import CACHE_DB

TTL = {
    "get_classes": 86400,        # 24h
    "get_timetable": 21600,      # 6h
    "get_tasks": 600,            # 10 min
    "get_task_detail": 1800,     # 30 min
    "get_files": 3600,           # 1h
    "get_journal": 1800,         # 30 min
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS request_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         INTEGER NOT NULL,
            tool       TEXT NOT NULL,
            args       TEXT NOT NULL,
            response   TEXT NOT NULL,
            source     TEXT NOT NULL DEFAULT 'mcp',
            duration_ms INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def get(key: str) -> Any | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    value, expires_at = row
    if time.time() > expires_at:
        return None
    return json.loads(value)


def set(key: str, value: Any, ttl_key: str) -> None:
    ttl = TTL.get(ttl_key, 600)
    expires_at = int(time.time()) + ttl
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), expires_at),
        )


def invalidate(key: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM cache WHERE key = ?", (key,))


def clear_all() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM cache")


def log_request(tool: str, args: dict, response: Any, source: str = "mcp", duration_ms: int = 0) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO request_log (ts, tool, args, response, source, duration_ms) VALUES (?,?,?,?,?,?)",
            (int(time.time()), tool, json.dumps(args), json.dumps(response), source, duration_ms),
        )
        # Keep only last 200 entries
        conn.execute("DELETE FROM request_log WHERE id NOT IN (SELECT id FROM request_log ORDER BY id DESC LIMIT 200)")


def get_request_log(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, ts, tool, args, response, source, duration_ms FROM request_log ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [
        {"id": r[0], "ts": r[1], "tool": r[2], "args": json.loads(r[3]),
         "response": json.loads(r[4]), "source": r[5], "duration_ms": r[6]}
        for r in rows
    ]


def get_cache_entries() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT key, value, expires_at FROM cache ORDER BY key"
        ).fetchall()
    now = int(time.time())
    return [
        {"key": r[0], "data": json.loads(r[1]),
         "expires_in_s": max(0, r[2] - now), "expired": r[2] < now}
        for r in rows
    ]
