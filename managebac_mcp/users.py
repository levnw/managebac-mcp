"""
Multi-user store: credentials (encrypted), tokens, and per-user session cookies.

Each user is identified by a secret token (the `?key=` in their connector URL).
Passwords are encrypted at rest with a Fernet key stored separately on disk.
Session cookies are stored per-user so no two users ever share a session.

Storage lives in ~/.managebac_mcp/users.db (separate from the response cache).
"""
import json
import secrets
import sqlite3
import time
from pathlib import Path

from cryptography.fernet import Fernet

from .config import DATA_DIR
from .context import User

USERS_DB = DATA_DIR / "users.db"
_KEY_FILE = DATA_DIR / "secret.key"


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

def _fernet() -> Fernet:
    """Load (or create) the symmetric key used to encrypt passwords at rest."""
    if not _KEY_FILE.exists():
        _KEY_FILE.write_bytes(Fernet.generate_key())
        _KEY_FILE.chmod(0o600)
    return Fernet(_KEY_FILE.read_bytes())


def _encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def _decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(USERS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              TEXT PRIMARY KEY,
            token           TEXT UNIQUE NOT NULL,
            label           TEXT,
            mb_url          TEXT NOT NULL,
            mb_email        TEXT NOT NULL,
            mb_password_enc TEXT NOT NULL,
            session_cookies TEXT,
            created_at      INTEGER NOT NULL
        )
    """)
    # Migration: add the 'enabled' column to older databases.
    cols = [c[1] for c in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "enabled" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
    conn.commit()
    return conn


def _row_to_user(row) -> User:
    return User(
        id=row[0],
        token=row[1],
        label=row[2],
        mb_url=row[3],
        email=row[4],
        password=_decrypt(row[5]),
    )


def create_user(label: str, mb_url: str, email: str, password: str) -> User:
    """Create a new user with a fresh random id + token. Returns the User."""
    user_id = secrets.token_hex(8)
    token = secrets.token_urlsafe(32)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (id, token, label, mb_url, mb_email, mb_password_enc, session_cookies, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, token, label, mb_url.rstrip("/"), email, _encrypt(password), None, int(time.time())),
        )
    return User(id=user_id, token=token, label=label, mb_url=mb_url.rstrip("/"), email=email, password=password)


def ensure_local_user(mb_url: str, email: str, password: str) -> User:
    """
    Upsert a fixed 'local' user from the operator's own .env credentials,
    used by the CLI (peek/submit/cache-view) for local testing. Isolated
    from enrolled users by its own user_id.
    """
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (id, token, label, mb_url, mb_email, mb_password_enc, session_cookies, created_at) "
            "VALUES ('local','local','local',?,?,?,NULL,?) "
            "ON CONFLICT(id) DO UPDATE SET mb_url=excluded.mb_url, mb_email=excluded.mb_email, "
            "mb_password_enc=excluded.mb_password_enc",
            (mb_url.rstrip("/"), email, _encrypt(password), int(time.time())),
        )
    return User(id="local", token="local", label="local",
                mb_url=mb_url.rstrip("/"), email=email, password=password)


def get_user_by_token(token: str) -> User | None:
    """Access-path lookup. Returns None for unknown OR disabled (paused) users."""
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, token, label, mb_url, mb_email, mb_password_enc FROM users "
            "WHERE token = ? AND enabled = 1",
            (token,),
        ).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_id(user_id: str) -> User | None:
    """Admin-path lookup. Returns the user regardless of enabled state."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, token, label, mb_url, mb_email, mb_password_enc FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return _row_to_user(row) if row else None


def set_enabled(user_id: str, enabled: bool) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET enabled = ? WHERE id = ?", (1 if enabled else 0, user_id))


def regenerate_token(user_id: str) -> str | None:
    """Rotate a user's secret token. Returns the new token, or None if not found."""
    new_token = secrets.token_urlsafe(32)
    with _connect() as conn:
        cur = conn.execute("UPDATE users SET token = ? WHERE id = ?", (new_token, user_id))
    return new_token if cur.rowcount == 1 else None


def get_user_by_email(mb_url: str, email: str) -> User | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, token, label, mb_url, mb_email, mb_password_enc FROM users WHERE mb_url = ? AND mb_email = ?",
            (mb_url.rstrip("/"), email),
        ).fetchone()
    return _row_to_user(row) if row else None


def update_password(user_id: str, password: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET mb_password_enc = ? WHERE id = ?", (_encrypt(password), user_id))


def list_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, label, mb_url, mb_email, created_at, token, enabled FROM users ORDER BY created_at"
        ).fetchall()
    return [
        {"id": r[0], "label": r[1], "mb_url": r[2], "email": r[3],
         "created_at": r[4], "token": r[5], "enabled": bool(r[6])}
        for r in rows
    ]


def delete_user(user_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ---------------------------------------------------------------------------
# Per-user session cookies
# ---------------------------------------------------------------------------

def load_cookies(user_id: str) -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT session_cookies FROM users WHERE id = ?", (user_id,)).fetchone()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return {}
    return {}


def save_cookies(user_id: str, cookies: dict) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET session_cookies = ? WHERE id = ?", (json.dumps(cookies), user_id))
