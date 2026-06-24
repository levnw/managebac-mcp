"""
Per-school branding for the enroll pages.

Each school's ManageBac has its own logo and name. Rather than hardcode them,
we read them straight off that school's own login page (every ManageBac login
renders `.school-logo img` and an `<h3>` with the school name) and cache the
result. A new school therefore needs zero manual setup — point it at its
ManageBac URL and the enroll pages brand themselves.
"""
import time

import httpx
from bs4 import BeautifulSoup

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_TTL = 24 * 3600
_CACHE: dict[str, tuple[float, dict]] = {}

# Shown when a school's login page can't be read (network error, unexpected
# markup). Neutral so the page still looks intentional.
_DEFAULT = {"name": "ManageBac", "logo": ""}


def normalize_url(mb_url: str) -> str:
    raw = (mb_url or "").strip()
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = "https://" + raw
    return raw.rstrip("/")


async def get_branding(mb_url: str) -> dict:
    """Return {"name", "logo"} for a school, cached for a day. Never raises."""
    base = normalize_url(mb_url)
    if not base:
        return dict(_DEFAULT)

    now = time.time()
    hit = _CACHE.get(base)
    if hit and now - hit[0] < _TTL:
        return hit[1]

    brand = dict(_DEFAULT)
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=10, headers={"User-Agent": _UA}
        ) as client:
            resp = await client.get(base + "/login")
        soup = BeautifulSoup(resp.text, "html.parser")
        img = soup.select_one(".school-logo img")
        if img and img.get("src"):
            brand["logo"] = img["src"]
        heading = soup.select_one(".content-block h3") or soup.find("h3")
        if heading:
            name = heading.get_text(strip=True)
            if name:
                brand["name"] = name
    except Exception:
        pass  # fall back to the neutral default

    _CACHE[base] = (now, brand)
    return brand
