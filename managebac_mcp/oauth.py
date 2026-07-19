"""
OAuth 2.1 authorization server + token store for the ChatGPT connector.

The server is BOTH the authorization server and the protected resource: the
/authorize page (see http_server.py) verifies a student's real ManageBac login,
then this module mints the authorization code and the opaque access/refresh
tokens that every /mcp request must carry as `Authorization: Bearer`.

Design notes:
- Opaque tokens, never JWTs — we are our own verifier, so a hashed lookup in
  SQLite is simpler, instantly revocable, and consistent with users.py/admin.py.
  Only SHA-256 hashes are stored; a leaked oauth.db exposes no usable secrets.
- PKCE S256 is mandatory (spec) and the only supported method.
- Clients come in two shapes:
    * CIMD — client_id IS an https URL (ChatGPT publishes its client metadata
      at a chatgpt.com URL). We fetch + cache that document for redirect URIs.
    * DCR  — POST /register stores ad-hoc clients (Claude, MCP Inspector).
- Refresh tokens rotate; reuse of a rotated token revokes the whole family
  (stolen-refresh-token detection per OAuth 2.1).
"""
import base64
import hashlib
import ipaddress
import json
import re
import secrets
import sqlite3
import time
from collections import deque
from urllib.parse import urlparse

from . import config, netguard, users
from .config import DATA_DIR

OAUTH_DB = DATA_DIR / "oauth.db"

SCOPE = "managebac"
CODE_TTL = 300                      # authorization codes: 5 minutes, single-use
ACCESS_TTL = 3600                   # access tokens: 1 hour
REFRESH_TTL = 90 * 24 * 3600        # refresh tokens: 90 days
CIMD_CACHE_TTL = 24 * 3600          # refetch ChatGPT's client doc daily
CIMD_MAX_BYTES = 64 * 1024

# Redirect URIs ChatGPT is known to use — allowed even if a CIMD fetch fails,
# so an outage on chatgpt.com's metadata endpoint can't lock users out.
_CHATGPT_REDIRECT_EXACT = "https://chatgpt.com/connector_platform_oauth_redirect"
_CHATGPT_REDIRECT_RE = re.compile(r"^https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]+$")


def _connect() -> sqlite3.Connection:
    conn = config.connect(OAUTH_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id     TEXT PRIMARY KEY,
            kind          TEXT NOT NULL,
            client_name   TEXT,
            redirect_uris TEXT NOT NULL,
            metadata      TEXT,
            created_at    INTEGER NOT NULL,
            fetched_at    INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_codes (
            code_hash      TEXT PRIMARY KEY,
            client_id      TEXT NOT NULL,
            user_id        TEXT NOT NULL,
            redirect_uri   TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            scope          TEXT NOT NULL DEFAULT 'managebac',
            resource       TEXT,
            created_at     INTEGER NOT NULL,
            expires_at     INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token_hash  TEXT PRIMARY KEY,
            kind        TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            client_id   TEXT NOT NULL,
            scope       TEXT NOT NULL,
            family_id   TEXT NOT NULL,
            created_at  INTEGER NOT NULL,
            expires_at  INTEGER NOT NULL,
            revoked     INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tokens_user   ON tokens(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tokens_family ON tokens(family_id)")
    conn.commit()
    return conn


def _hash(tok: str) -> str:
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Clients — DCR store + CIMD fetch
# ---------------------------------------------------------------------------

def _valid_redirect_uri(uri: str) -> bool:
    """https anywhere, or http on loopback (MCP Inspector dev flows)."""
    try:
        p = urlparse(uri)
    except ValueError:
        return False
    if p.scheme == "https" and p.netloc:
        return True
    if p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    return False


def register_dcr_client(metadata: dict) -> dict | None:
    """Auto-approve dynamic client registration (RFC 7591). Returns the
    registration response dict, or None if the metadata is unacceptable."""
    if not isinstance(metadata, dict):
        return None
    uris = metadata.get("redirect_uris")
    if not isinstance(uris, list) or not uris:
        return None
    uris = [u for u in uris if isinstance(u, str)]
    if not uris or not all(_valid_redirect_uri(u) for u in uris):
        return None

    client_id = "dcr_" + secrets.token_hex(16)
    now = int(time.time())
    name = str(metadata.get("client_name") or "")[:120]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO clients (client_id, kind, client_name, redirect_uris, metadata, created_at) "
            "VALUES (?, 'dcr', ?, ?, ?, ?)",
            (client_id, name, json.dumps(uris), json.dumps(metadata)[:8192], now),
        )
        conn.commit()
    return {
        "client_id": client_id,
        "client_id_issued_at": now,
        "client_name": name or None,
        "redirect_uris": uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }


def get_stored_client(client_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT client_id, kind, client_name, redirect_uris, fetched_at "
            "FROM clients WHERE client_id = ?", (client_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "client_id": row[0], "kind": row[1], "client_name": row[2],
        "redirect_uris": json.loads(row[3] or "[]"), "fetched_at": row[4],
    }


def _cimd_url_acceptable(client_id: str) -> bool:
    """CIMD client_ids must be plain https URLs on a real public host."""
    try:
        p = urlparse(client_id)
    except ValueError:
        return False
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        return False
    host = p.hostname.lower()
    if host in ("localhost",) or host.endswith(".local"):
        return False
    try:
        ipaddress.ip_address(host)
        return False            # no IP-literal client ids
    except ValueError:
        pass
    return True


async def resolve_client(client_id: str) -> dict | None:
    """Look up a client: DCR by id, else CIMD (client_id is an https URL —
    fetch its metadata document, cached 24h, stale-if-error)."""
    if not client_id:
        return None
    stored = get_stored_client(client_id)
    if stored and stored["kind"] == "dcr":
        return stored

    if not _cimd_url_acceptable(client_id):
        return stored            # unknown non-URL client id -> None

    now = int(time.time())
    if stored and stored["fetched_at"] and now - stored["fetched_at"] < CIMD_CACHE_TTL:
        return stored

    doc = None
    try:
        # SSRF guard: client_id is an attacker-supplied URL. netguard rejects
        # non-public hosts and re-validates redirect hops (an https CIMD doc
        # must stay https), so this fetch can't be aimed at internal addresses.
        resp = await netguard.safe_get(client_id, require_https=True,
                                       headers={"Accept": "application/json"}, timeout=10)
        if resp.status_code == 200 and len(resp.content) <= CIMD_MAX_BYTES:
            doc = resp.json()
    except Exception:
        doc = None

    if isinstance(doc, dict):
        # If the document names its own client_id it must match the URL.
        if doc.get("client_id") and doc["client_id"] != client_id:
            doc = None

    if isinstance(doc, dict):
        uris = [u for u in (doc.get("redirect_uris") or [])
                if isinstance(u, str) and u.startswith("https://")]
        name = str(doc.get("client_name") or "")[:120]
        with _connect() as conn:
            conn.execute(
                "INSERT INTO clients (client_id, kind, client_name, redirect_uris, metadata, created_at, fetched_at) "
                "VALUES (?, 'cimd', ?, ?, ?, ?, ?) "
                "ON CONFLICT(client_id) DO UPDATE SET client_name=excluded.client_name, "
                "redirect_uris=excluded.redirect_uris, metadata=excluded.metadata, fetched_at=excluded.fetched_at",
                (client_id, name, json.dumps(uris), json.dumps(doc)[:8192], now, now),
            )
            conn.commit()
        return get_stored_client(client_id)

    # Fetch failed: serve the stale cached row if we have one; else, for
    # chatgpt.com client ids, fall back to the hard-allowlisted redirects so a
    # metadata outage can't block sign-in.
    if stored:
        return stored
    host = (urlparse(client_id).hostname or "").lower()
    if host == "chatgpt.com" or host.endswith(".chatgpt.com"):
        return {"client_id": client_id, "kind": "cimd", "client_name": "ChatGPT",
                "redirect_uris": [], "fetched_at": None}
    return None


def redirect_uri_allowed(client: dict, redirect_uri: str) -> bool:
    """Exact-match against the client's registered/published URIs, plus the
    hard-allowlisted ChatGPT redirect patterns for chatgpt.com CIMD clients."""
    if not redirect_uri:
        return False
    if redirect_uri in (client.get("redirect_uris") or []):
        return True
    if client.get("kind") == "cimd":
        host = (urlparse(client.get("client_id") or "").hostname or "").lower()
        if host == "chatgpt.com" or host.endswith(".chatgpt.com"):
            if redirect_uri == _CHATGPT_REDIRECT_EXACT:
                return True
            if _CHATGPT_REDIRECT_RE.match(redirect_uri):
                return True
    return False


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------

def verify_pkce(verifier: str, challenge: str) -> bool:
    if not verifier or not challenge:
        return False
    digest = hashlib.sha256(verifier.encode("ascii", "ignore")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(computed, challenge)


# ---------------------------------------------------------------------------
# Authorization codes
# ---------------------------------------------------------------------------

def create_auth_code(*, user_id: str, client_id: str, redirect_uri: str,
                     code_challenge: str, scope: str = SCOPE,
                     resource: str | None = None) -> str:
    code = "mbc_" + secrets.token_urlsafe(32)
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_codes (code_hash, client_id, user_id, redirect_uri, "
            "code_challenge, scope, resource, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_hash(code), client_id, user_id, redirect_uri, code_challenge,
             scope, resource, now, now + CODE_TTL),
        )
        conn.commit()
    return code


def consume_auth_code(code: str) -> dict | None:
    """Atomically fetch-and-delete. Returns None for unknown/expired/reused."""
    if not code:
        return None
    h = _hash(code)
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute(
            "SELECT client_id, user_id, redirect_uri, code_challenge, scope, resource, expires_at "
            "FROM auth_codes WHERE code_hash = ?", (h,),
        ).fetchone()
        conn.execute("DELETE FROM auth_codes WHERE code_hash = ?", (h,))
        conn.execute("DELETE FROM auth_codes WHERE expires_at < ?", (now,))  # gc
        conn.commit()
    if row is None or row[6] < now:
        return None
    return {"client_id": row[0], "user_id": row[1], "redirect_uri": row[2],
            "code_challenge": row[3], "scope": row[4], "resource": row[5]}


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def issue_tokens(*, user_id: str, client_id: str, scope: str = SCOPE,
                 family_id: str | None = None) -> dict:
    access = "mba_" + secrets.token_urlsafe(32)
    refresh = "mbr_" + secrets.token_urlsafe(32)
    family = family_id or secrets.token_hex(8)
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO tokens (token_hash, kind, user_id, client_id, scope, family_id, created_at, expires_at) "
            "VALUES (?, 'access', ?, ?, ?, ?, ?, ?)",
            (_hash(access), user_id, client_id, scope, family, now, now + ACCESS_TTL),
        )
        conn.execute(
            "INSERT INTO tokens (token_hash, kind, user_id, client_id, scope, family_id, created_at, expires_at) "
            "VALUES (?, 'refresh', ?, ?, ?, ?, ?, ?)",
            (_hash(refresh), user_id, client_id, scope, family, now, now + REFRESH_TTL),
        )
        conn.commit()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
        "refresh_token": refresh,
        "scope": scope,
    }


def rotate_refresh(refresh_token: str, client_id: str) -> dict | None:
    """Rotate a refresh token. Reuse of an already-rotated (revoked) token is
    treated as theft: the entire token family is revoked. Returns the new
    token response dict or None."""
    if not refresh_token:
        return None
    h = _hash(refresh_token)
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id, client_id, scope, family_id, expires_at, revoked "
            "FROM tokens WHERE token_hash = ? AND kind = 'refresh'", (h,),
        ).fetchone()
        if row is None:
            return None
        user_id, tok_client, scope, family, expires_at, revoked = row
        if revoked:
            # Reuse detected — revoke everything in this family.
            conn.execute("UPDATE tokens SET revoked = 1 WHERE family_id = ?", (family,))
            conn.commit()
            return None
        if expires_at < now or tok_client != client_id:
            return None
        conn.execute("UPDATE tokens SET revoked = 1 WHERE token_hash = ?", (h,))
        conn.execute(  # gc: drop long-expired rows opportunistically
            "DELETE FROM tokens WHERE expires_at < ?", (now - 7 * 24 * 3600,))
        conn.commit()
    return issue_tokens(user_id=user_id, client_id=client_id, scope=scope, family_id=family)


def user_for_access_token(token: str):
    """Map a Bearer access token to a User (via users.get_user_by_id, which
    includes paused users so the in-tool suspension intercept still runs).
    Returns None for unknown/expired/revoked tokens or deleted users."""
    if not token or not token.startswith("mba_"):
        return None
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM tokens WHERE token_hash = ? AND kind = 'access' "
            "AND revoked = 0 AND expires_at >= ?", (_hash(token), now),
        ).fetchone()
    if row is None:
        return None
    return users.get_user_by_id(row[0])


def revoke_user_tokens(user_id: str) -> None:
    """Sign a user out everywhere (admin delete / regenerate)."""
    with _connect() as conn:
        conn.execute("UPDATE tokens SET revoked = 1 WHERE user_id = ?", (user_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Rate limiting (authorize POST — password + invite brute force)
# ---------------------------------------------------------------------------

_RATE_MAX = 10
_RATE_WINDOW = 300
_rate: dict[str, deque] = {}


def check_rate(ip: str) -> bool:
    """True if this IP is still within the allowance (10 attempts / 5 min)."""
    now = time.time()
    q = _rate.setdefault(ip or "unknown", deque())
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_MAX:
        return False
    q.append(now)
    if len(_rate) > 10000:      # unbounded-dict guard
        _rate.clear()
    return True
