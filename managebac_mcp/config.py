import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

# Look for .env in multiple locations — works regardless of where package is installed
_ENV_LOCATIONS = [
    Path.home() / ".managebac_mcp" / ".env",   # preferred: ~/.managebac_mcp/.env
    Path(__file__).parent.parent / ".env",       # project root (dev mode)
]
for _env_path in _ENV_LOCATIONS:
    if _env_path.exists():
        load_dotenv(_env_path)
        break
else:
    load_dotenv()  # fallback: let dotenv search upward from CWD

BASE_URL = os.environ.get("MANAGEBAC_URL", "https://es.managebac.com")
EMAIL = os.environ.get("MANAGEBAC_EMAIL", "")
PASSWORD = os.environ.get("MANAGEBAC_PASSWORD", "")

# Optional invite code for the self-service /enroll page. If set, new users
# must enter it to enroll — stops strangers using your server as a free proxy.
SIGNUP_CODE = os.environ.get("MANAGEBAC_SIGNUP_CODE", "")

DATA_DIR = Path.home() / ".managebac_mcp"
SESSION_FILE = DATA_DIR / "session.json"
CACHE_DB = DATA_DIR / "cache.db"

# Ensure the config directory exists
DATA_DIR.mkdir(exist_ok=True)


class _SelfClosingConnection(sqlite3.Connection):
    """A sqlite3 connection that also CLOSES on `with` exit, not just commits.

    Plain `with sqlite3.connect(...) as conn:` commits/rolls back but leaves the
    connection (and its file descriptor) open. Every cache/users/admin call
    opened one and never closed it, so fds leaked until the process hit its
    limit and sqlite started failing with 'unable to open database file' — which
    took the whole server down with 502s. Closing on exit fixes the leak.
    """
    def __exit__(self, *exc):
        try:
            super().__exit__(*exc)   # commit on success, rollback on error
        finally:
            self.close()


def connect(path) -> sqlite3.Connection:
    """Open a sqlite connection that commits AND closes when used as a context
    manager (`with config.connect(path) as conn:`). Also sets WAL + a busy
    timeout so concurrent access doesn't error out under load."""
    conn = sqlite3.connect(path, factory=_SelfClosingConnection, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
