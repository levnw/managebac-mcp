"""Shared HTTP setup, input validation and safe network errors; no school data extraction."""
import re
from urllib.parse import urlsplit
import httpx
from diagnostics import event
from bs4 import BeautifulSoup

USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

class FlowError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def school_origin(url):
    p = urlsplit(url)
    if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
            or not re.fullmatch(r"[a-z0-9-]+\.managebac\.(com|cn)", p.hostname or "")):
        raise FlowError("unsafe_destination", "ManageBac returned an unexpected school address.")
    return f"https://{p.hostname}"


def email_value(value):
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise FlowError("invalid_email", "Enter your complete ManageBac email address.")
    return value


def soup_of(response):
    if response.status_code == 429:
        raise FlowError("rate_limited", "ManageBac is limiting requests. Wait before trying again.")
    if response.status_code != 200:
        raise FlowError("upstream_unavailable", "ManageBac could not serve this page. No data was changed.")
    return BeautifulSoup(response.text, "html.parser")


class Transport:
    def __init__(self, transport=None):
        self.transport = transport

    def client(self):
        async def request_hook(request):
            event('http.request')
        async def response_hook(response):
            event('http.response', status=response.status_code)
        # A small keep-alive pool: sessions now reuse one client across tool calls.
        return httpx.AsyncClient(transport=self.transport, timeout=20, follow_redirects=False,
                                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4,
                                                    keepalive_expiry=60),
                                headers={"User-Agent": USER_AGENT},
                                event_hooks={'request':[request_hook], 'response':[response_hook]})
