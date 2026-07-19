"""
SSRF egress guard for the two places the server fetches a user-influenced URL:
the CIMD client-metadata document (oauth.py) and a school's login page for
branding (branding.py). Both take a URL that ultimately comes from an
unauthenticated request, so without a guard they can be pointed at internal /
link-local / loopback addresses (e.g. cloud metadata at 169.254.169.254).

`safe_get` resolves the host and refuses to connect if *any* resolved address
is non-global, and it re-validates every redirect hop (so a public host can't
302 into internal space). Callers keep their own body-size / JSON handling.
"""
import asyncio
import ipaddress
from urllib.parse import urlparse

import httpx


class UnsafeURLError(Exception):
    """Raised when a URL's host is not safe to fetch (non-public / bad scheme)."""


async def _assert_safe_url(url: str, *, require_https: bool) -> None:
    p = urlparse(url)
    scheme = (p.scheme or "").lower()
    allowed = ("https",) if require_https else ("http", "https")
    if scheme not in allowed:
        raise UnsafeURLError(f"disallowed scheme: {scheme!r}")
    host = p.hostname
    if not host:
        raise UnsafeURLError("missing host")

    port = p.port or (443 if scheme == "https" else 80)
    loop = asyncio.get_event_loop()
    try:
        infos = await loop.getaddrinfo(host, port, proto=6)  # IPPROTO_TCP
    except OSError as e:
        raise UnsafeURLError(f"cannot resolve host {host!r}: {e}")
    if not infos:
        raise UnsafeURLError(f"host {host!r} did not resolve")

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise UnsafeURLError(f"host {host!r} resolved to non-IP {addr!r}")
        # is_global is False for private, loopback, link-local, shared (CGNAT),
        # and reserved ranges — exactly the addresses we must not reach.
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURLError(f"host {host!r} resolves to non-public address {addr}")


async def safe_get(
    url: str,
    *,
    require_https: bool = False,
    headers: dict | None = None,
    timeout: float = 10,
    max_redirects: int = 3,
) -> httpx.Response:
    """GET a URL with SSRF protection. Validates the host (and every redirect
    hop) against the private/loopback/link-local ranges before connecting.
    Raises UnsafeURLError if any hop is unsafe or redirects run too deep."""
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, headers=headers or {}) as client:
        current = url
        for _ in range(max_redirects + 1):
            await _assert_safe_url(current, require_https=require_https)
            resp = await client.get(current)
            if resp.is_redirect and resp.next_request is not None:
                current = str(resp.next_request.url)
                continue
            return resp
    raise UnsafeURLError("too many redirects")
