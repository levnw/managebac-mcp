"""
HTTP transport for the ManageBac MCP server.

Exposes the exact same tools as the stdio server (server.py) over
Streamable HTTP, so remote clients like ChatGPT can connect to a public URL
(e.g. via a Cloudflare Tunnel) instead of launching a local process.

Protected by a secret bearer token — anyone with the token can read the
account, so the URL must stay private. The token is checked at the ASGI
layer (not BaseHTTPMiddleware) so it never buffers the streaming response.

Run with:  managebac-mcp serve --port 8000
"""
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import Scope, Receive, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from .server import server


def _provided_token(scope: Scope) -> str | None:
    """Extract a token from the Authorization header or ?key= query string."""
    # Headers — list of (bytes, bytes)
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            v = value.decode("latin-1")
            if v.lower().startswith("bearer "):
                return v[7:].strip()
    # Query string fallback (?key=TOKEN) — for clients that can't set headers
    qs = scope.get("query_string", b"").decode("latin-1")
    for pair in qs.split("&"):
        if pair.startswith("key="):
            from urllib.parse import unquote
            return unquote(pair[4:])
    return None


def build_app(token: str, *, stateless: bool = True) -> Starlette:
    """Build the Starlette ASGI app serving MCP over Streamable HTTP."""
    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=stateless,
        json_response=False,
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        # Token check at the ASGI layer — no response buffering.
        if token and _provided_token(scope) != token:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"error":"unauthorized - missing or invalid token"}',
            })
            return
        await session_manager.handle_request(scope, receive, send)

    async def health(request):
        return PlainTextResponse("ManageBac MCP server is running.")

    @asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/", health, methods=["GET"]),
            Mount("/mcp", app=handle_mcp),
        ],
        lifespan=lifespan,
    )


def run(host: str = "127.0.0.1", port: int = 8000, token: str = "") -> None:
    """Run the HTTP server with uvicorn (blocking)."""
    import uvicorn
    app = build_app(token)
    uvicorn.run(app, host=host, port=port, log_level="info")
