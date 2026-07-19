"""
SSRF egress guard for the two places the server fetches a user-influenced URL:
the CIMD client-metadata document (oauth.py) and a school's login page for
branding (branding.py). Both take a URL that ultimately comes from an
unauthenticated request, so without a guard they can be pointed at internal /
link-local / loopback addresses (e.g. cloud metadata at 169.254.169.254).

`safe_get` resolves the host, refuses to connect unless *every* resolved
address is public, then connects to the validated IP directly (pinned) so the
name can't be rebound to a private address between the check and the connect.
The real hostname is preserved in the Host header and TLS SNI, so certificate
verification is unaffected. Redirects are followed manually and re-validated.
"""
import asyncio
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx


class UnsafeURLError(Exception):
    """Raised when a URL's host is not safe to fetch (non-public / bad scheme)."""


def _check_ip(host: str, addr: str) -> None:
    """Reject a resolved address unless it is globally routable."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        raise UnsafeURLError(f"host {host!r} resolved to non-IP {addr!r}")
    # Unwrap IPv4-mapped IPv6 (::ffff:a.b.c.d) so a mapped private address can't
    # slip past is_global on interpreters that don't unwrap it themselves.
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global is False for private, loopback, link-local, shared (CGNAT), and
    # reserved ranges — exactly the addresses we must not reach.
    if not ip.is_global or ip.is_multicast:
        raise UnsafeURLError(f"host {host!r} resolves to non-public address {addr}")


async def _resolve_public(host: str, port: int) -> str:
    """Resolve `host`, require EVERY address to be public, and return one
    validated IP to connect to (pinning it closes the DNS-rebinding window)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, proto=6)  # IPPROTO_TCP
    except OSError as e:
        raise UnsafeURLError(f"cannot resolve host {host!r}: {e}")
    if not infos:
        raise UnsafeURLError(f"host {host!r} did not resolve")
    addrs = [info[4][0] for info in infos]
    for addr in addrs:
        _check_ip(host, addr)
    return addrs[0]


def _bracket(host_or_ip: str) -> str:
    """Wrap an IPv6 literal in [] for use in a URL authority / Host header."""
    return f"[{host_or_ip}]" if ":" in host_or_ip else host_or_ip


async def safe_get(
    url: str,
    *,
    require_https: bool = False,
    headers: dict | None = None,
    timeout: float = 10,
    max_redirects: int = 3,
) -> httpx.Response:
    """GET a URL with SSRF protection. For each hop it resolves the host,
    rejects it unless *every* resolved address is public, then connects to the
    validated IP directly (pinned — no re-resolution) while preserving the Host
    header and TLS SNI so certificate verification still checks the real host.
    Redirects are followed manually and each hop is re-validated. Raises
    UnsafeURLError if any hop is unsafe or redirects run too deep."""
    base_headers = dict(headers or {})
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        logical = url
        for _ in range(max_redirects + 1):
            p = urlparse(logical)
            scheme = (p.scheme or "").lower()
            allowed = ("https",) if require_https else ("http", "https")
            if scheme not in allowed:
                raise UnsafeURLError(f"disallowed scheme: {scheme!r}")
            host = p.hostname
            if not host:
                raise UnsafeURLError("missing host")
            port = p.port or (443 if scheme == "https" else 80)

            ip = await _resolve_public(host, port)

            # Connect to the validated IP directly; keep the real host in the
            # Host header and (for TLS) the SNI hostname so the cert is still
            # verified against the real hostname, not the IP.
            authority = _bracket(host) if p.port is None else f"{_bracket(host)}:{p.port}"
            ip_netloc = _bracket(ip) if p.port is None else f"{_bracket(ip)}:{p.port}"
            connect_url = p._replace(netloc=ip_netloc).geturl()

            req_headers = dict(base_headers)
            req_headers["Host"] = authority
            extensions = {"sni_hostname": host} if scheme == "https" else {}

            resp = await client.get(connect_url, headers=req_headers, extensions=extensions)

            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    return resp
                logical = urljoin(logical, loc)   # resolve Location against the REAL host
                continue
            return resp
    raise UnsafeURLError("too many redirects")
