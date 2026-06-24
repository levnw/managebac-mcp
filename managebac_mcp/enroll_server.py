"""
Keyless "enroll" MCP server — the in-chat onboarding flow.

A student who hasn't connected yet adds ONE public connector (no ?key=) which
exposes a single tool: `enroll`. They say "enroll me", the tool collects their
school URL + email + invite code, and hands back a one-time secure link where
they type their ManageBac password directly into our server. The password never
travels through ChatGPT — only the school URL, email, and invite code do.

This is a separate MCP Server from the data server in server.py: the data
server fails closed without a user context, so it can't host an anonymous tool.
"""
from mcp.server import Server
from mcp import types

from . import admin, users

ENROLL_INSTRUCTIONS = (
    "This connector onboards a student to the ManageBac assistant. The student is "
    "NOT connected yet — the only thing you can do here is enroll them.\n"
    "\n"
    "When the student asks to connect / enroll / sign up:\n"
    "- Call the `enroll` tool with their school ManageBac URL, their ManageBac login "
    "email, and the invite code they were given.\n"
    "- If they don't know their school URL, the default es.managebac.com is used.\n"
    "- NEVER ask for or accept their ManageBac password in chat. The `enroll` tool "
    "returns a private link; tell the student to open it and type their password there. "
    "Their password must only ever be entered on that page, never sent to you.\n"
    "- After they finish on that page they get a personal connector link to add as a "
    "second connector. From then on they use that one, not this enroll connector."
)

enroll_server = Server("managebac-enroll", instructions=ENROLL_INSTRUCTIONS)

_PUBLIC_URL = "http://localhost:8000"


def set_enroll_public_url(url: str) -> None:
    global _PUBLIC_URL
    _PUBLIC_URL = url.rstrip("/")


def _normalize_mb_url(raw: str) -> str:
    from urllib.parse import urlparse
    raw = (raw or "").strip()
    if not raw:
        return "https://es.managebac.com"
    if not raw.startswith("http"):
        raw = "https://" + raw
    parsed = urlparse(raw)
    return f"{parsed.scheme}://{parsed.netloc}"


@enroll_server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="enroll",
            description=(
                "Start connecting the student's ManageBac account to this assistant. "
                "Provide their school ManageBac URL, their ManageBac login email, and "
                "their invite code. Returns a private one-time link where the student "
                "enters their ManageBac password to finish. IMPORTANT: never ask for or "
                "pass the student's password here — the password is only ever entered on "
                "the returned link, not in chat."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "The student's ManageBac login email.",
                    },
                    "invite_code": {
                        "type": "string",
                        "description": "The one-time invite code the admin gave the student.",
                    },
                    "mb_url": {
                        "type": "string",
                        "description": "The school's ManageBac URL, e.g. https://es.managebac.com. Defaults to es.managebac.com if omitted.",
                    },
                },
                "required": ["email", "invite_code"],
            },
        )
    ]


@enroll_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "enroll":
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    email = (arguments.get("email") or "").strip()
    invite = (arguments.get("invite_code") or arguments.get("invite") or "").strip()
    mb_url = _normalize_mb_url(arguments.get("mb_url") or "")

    if not email:
        return [types.TextContent(type="text", text=(
            "I need the student's ManageBac login email to start. Ask them for it. "
            "Do NOT ask for their password — that's entered later on a secure page."
        ))]

    existing = users.get_user_by_email(mb_url, email)
    if not existing and not invite:
        return [types.TextContent(type="text", text=(
            "A one-time invite code is required to connect. Ask the student for the "
            "code their admin gave them, then call `enroll` again with it."
        ))]
    if not existing and not admin.code_unused(invite):
        return [types.TextContent(type="text", text=(
            "That invite code is invalid or has already been used. Ask the student to "
            "double-check it or request a new one from the admin."
        ))]

    token = admin.create_pending(mb_url, email, invite)
    link = f"{_PUBLIC_URL}/set-password?t={token}"

    verb = "reconnect" if existing else "finish connecting"
    text = (
        f"Almost there. To {verb} **{email}** at {mb_url}, the student needs to open "
        f"this private link and enter their ManageBac password there:\n\n{link}\n\n"
        "Tell them: open that link, type your ManageBac password, and you'll get your "
        "personal connector link to add to ChatGPT. The link works once and expires in "
        "30 minutes. Do not type your password here in chat — only on that page."
    )
    return [types.TextContent(type="text", text=text)]
