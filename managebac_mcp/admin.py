"""
Admin store: the operator's login, session tokens, and one-time invite codes.

Kept in its own SQLite db (~/.managebac_mcp/admin.db) separate from user data.
Passwords are salted + PBKDF2-hashed; sessions are random bearer tokens.
"""
import hashlib
import secrets
import sqlite3
import time

from . import config
from .config import DATA_DIR

ADMIN_DB = DATA_DIR / "admin.db"

_SESSION_TTL = 30 * 24 * 3600   # 30 days
_PBKDF2_ROUNDS = 200_000


def _connect() -> sqlite3.Connection:
    conn = config.connect(ADMIN_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            username TEXT PRIMARY KEY,
            pw_salt  TEXT NOT NULL,
            pw_hash  TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_sessions (
            token      TEXT PRIMARY KEY,
            username   TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            code       TEXT PRIMARY KEY,
            note       TEXT,
            created_at INTEGER NOT NULL,
            used_by    TEXT,
            used_email TEXT,
            used_at    INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_enrollments (
            token      TEXT PRIMARY KEY,
            mb_url     TEXT NOT NULL,
            email      TEXT NOT NULL,
            invite     TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            text           TEXT NOT NULL,
            target_user_id TEXT,
            created_at     INTEGER NOT NULL,
            read_by        TEXT
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Admin credentials
# ---------------------------------------------------------------------------

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()


def set_admin(username: str, password: str) -> None:
    salt = secrets.token_hex(16)
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admins (username, pw_salt, pw_hash, created_at) VALUES (?,?,?,?)",
            (username, salt, _hash(password, salt), int(time.time())),
        )


def has_admin() -> bool:
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone() is not None


def verify_admin(username: str, password: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT pw_salt, pw_hash FROM admins WHERE username = ?", (username,)).fetchone()
    if not row:
        return False
    salt, expected = row
    return secrets.compare_digest(_hash(password, salt), expected)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(username: str) -> dict:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires = now + _SESSION_TTL
    with _connect() as conn:
        conn.execute(
            "INSERT INTO admin_sessions (token, username, created_at, expires_at) VALUES (?,?,?,?)",
            (token, username, now, expires),
        )
    return {"token": token, "expires_at": expires}


def validate_session(token: str) -> str | None:
    """Return the admin username for a valid, unexpired token, else None."""
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, expires_at FROM admin_sessions WHERE token = ?", (token,)
        ).fetchone()
    if not row:
        return None
    username, expires_at = row
    if time.time() > expires_at:
        return None
    return username


def revoke_session(token: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


# ---------------------------------------------------------------------------
# One-time invite codes
# ---------------------------------------------------------------------------

def create_code(note: str = "") -> dict:
    code = secrets.token_hex(4)   # 8 hex chars — short + typeable
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO invite_codes (code, note, created_at) VALUES (?,?,?)",
            (code, note, now),
        )
    return {"code": code, "note": note, "created_at": now, "used": False}


def list_codes() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT code, note, created_at, used_by, used_email, used_at FROM invite_codes ORDER BY created_at DESC"
        ).fetchall()
    return [
        {"code": r[0], "note": r[1] or "", "created_at": r[2],
         "used": r[3] is not None, "used_email": r[4], "used_at": r[5]}
        for r in rows
    ]


def code_unused(code: str) -> bool:
    """True if the code exists and has not been redeemed yet."""
    if not code:
        return False
    with _connect() as conn:
        row = conn.execute("SELECT used_by FROM invite_codes WHERE code = ?", (code,)).fetchone()
    return row is not None and row[0] is None


def redeem_code(code: str, user_id: str, email: str) -> bool:
    """
    Atomically mark a one-time code as used. Returns True if the code was valid
    and unused (and is now consumed), False otherwise.
    """
    now = int(time.time())
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE invite_codes SET used_by = ?, used_email = ?, used_at = ? "
            "WHERE code = ? AND used_by IS NULL",
            (user_id, email, now, code),
        )
        conn.commit()
        return cur.rowcount == 1


def delete_code(code: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM invite_codes WHERE code = ?", (code,))


# ---------------------------------------------------------------------------
# Pending enrollments (in-chat enroll → secure password link handoff)
# ---------------------------------------------------------------------------

_PENDING_TTL = 30 * 60   # 30 minutes to open the link and set a password


def create_pending(mb_url: str, email: str, invite: str, ttl: int = _PENDING_TTL) -> str:
    """Stash an in-progress enrollment and return its one-time token."""
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pending_enrollments (token, mb_url, email, invite, created_at, expires_at) "
            "VALUES (?,?,?,?,?,?)",
            (token, mb_url, email, invite, now, now + ttl),
        )
    return token


def get_pending(token: str) -> dict | None:
    """Return the pending enrollment if the token exists and hasn't expired."""
    if not token:
        return None
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute(
            "SELECT mb_url, email, invite, expires_at FROM pending_enrollments WHERE token = ?",
            (token,),
        ).fetchone()
    if row is None or row[3] < now:
        return None
    return {"mb_url": row[0], "email": row[1], "invite": row[2], "expires_at": row[3]}


def delete_pending(token: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM pending_enrollments WHERE token = ?", (token,))
        conn.execute("DELETE FROM pending_enrollments WHERE expires_at < ?", (int(time.time()),))


# ---------------------------------------------------------------------------
# Admin messages (broadcast or per-user)
# ---------------------------------------------------------------------------

def create_message(text: str, target_user_id: str | None = None) -> dict:
    now = int(time.time())
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO messages (text, target_user_id, created_at) VALUES (?,?,?)",
            (text, target_user_id, now),
        )
        msg_id = cur.lastrowid
    return {"id": msg_id, "text": text, "target_user_id": target_user_id, "created_at": now}


def list_messages(user_id: str | None = None) -> list[dict]:
    with _connect() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT id, text, target_user_id, created_at FROM messages "
                "WHERE target_user_id IS NULL OR target_user_id = ? ORDER BY id DESC LIMIT 100",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, text, target_user_id, created_at FROM messages ORDER BY id DESC LIMIT 100"
            ).fetchall()
    return [{"id": r[0], "text": r[1], "target_user_id": r[2], "created_at": r[3]} for r in rows]
