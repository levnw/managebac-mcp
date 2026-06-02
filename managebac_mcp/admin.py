"""
Admin store: the operator's login, session tokens, and one-time invite codes.

Kept in its own SQLite db (~/.managebac_mcp/admin.db) separate from user data.
Passwords are salted + PBKDF2-hashed; sessions are random bearer tokens.
"""
import hashlib
import secrets
import sqlite3
import time

from .config import DATA_DIR

ADMIN_DB = DATA_DIR / "admin.db"

_SESSION_TTL = 30 * 24 * 3600   # 30 days
_PBKDF2_ROUNDS = 200_000


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(ADMIN_DB)
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
