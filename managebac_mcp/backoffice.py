"""
Back-office / operator data layer: one-time invite codes (which gate every new
student's OAuth sign-in), operator messages (surfaced by the tool intercept),
an audit log, and dormant admin-login credentials for a future admin panel.

There is no admin panel UI anymore — this is just the data these operator
features read/write. The DB file is still named `admin.db` (kept for
backwards-compat with already-deployed data, which holds live invite codes).
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
        CREATE TABLE IF NOT EXISTS messages (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            text           TEXT NOT NULL,
            target_user_id TEXT,
            created_at     INTEGER NOT NULL,
            read_by        TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            actor      TEXT NOT NULL,
            action     TEXT NOT NULL,
            detail     TEXT,
            created_at INTEGER NOT NULL
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
# Audit log
# ---------------------------------------------------------------------------

def log_audit(actor: str, action: str, detail: dict | None = None) -> None:
    import json as _json
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor, action, detail, created_at) VALUES (?,?,?,?)",
            (actor, action, _json.dumps(detail) if detail else None, int(time.time())),
        )


def list_audit(limit: int = 200) -> list[dict]:
    import json as _json
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, actor, action, detail, created_at FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        detail = None
        if r[3]:
            try:
                detail = _json.loads(r[3])
            except Exception:
                detail = r[3]
        result.append({"id": r[0], "actor": r[1], "action": r[2], "detail": detail, "created_at": r[4]})
    return result


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


def pop_message(user_id: str) -> str | None:
    """Return and consume the next unread message for this user, or None.

    Targeted messages (target_user_id = user_id) are deleted on delivery.
    Broadcast messages (target_user_id IS NULL) are marked read per-user via
    a comma-separated read_by column — so every user gets each broadcast once.
    Targeted messages take priority over broadcasts.
    """
    with _connect() as conn:
        # Priority 1: targeted message for this specific user
        row = conn.execute(
            "SELECT id, text FROM messages WHERE target_user_id = ? ORDER BY id LIMIT 1",
            (user_id,),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM messages WHERE id = ?", (row[0],))
            conn.commit()
            return row[1]

        # Priority 2: broadcast not yet read by this user
        row = conn.execute(
            "SELECT id, text, read_by FROM messages WHERE target_user_id IS NULL ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            msg_id, text, read_by = row
            already_read = set((read_by or "").split(",")) if read_by else set()
            if user_id not in already_read:
                already_read.add(user_id)
                conn.execute(
                    "UPDATE messages SET read_by = ? WHERE id = ?",
                    (",".join(already_read), msg_id),
                )
                conn.commit()
                return text
    return None


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
