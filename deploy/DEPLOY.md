# Deploying the ManageBac MCP server

Production runs on a **headless macOS** box (user `server`) with two launchd
LaunchDaemons — the MCP server and a Cloudflare Tunnel — exposing it at
**https://managebac.822538.xyz**. Students add one connector in ChatGPT and sign
in with their ManageBac account (OAuth 2.1).

> This describes the real setup. (There is a Linux/systemd variant too, but it is
> not what production uses.)

---

## Overview

```
ChatGPT  ──HTTPS──>  Cloudflare  ──tunnel "genesis"──>  cloudflared (on the Mac)
                                                              │
                                                              └─> 127.0.0.1:8000  (managebac-mcp serve)
```

The MCP server only listens on `127.0.0.1` — never exposed to the internet
directly. Cloudflare reaches it through the tunnel, so there are no inbound ports
to open.

---

## Access

The server Mac is reached over **Tailscale SSH**:

```bash
ssh server@100.77.121.118          # first connect each session may need a browser re-auth
```

Repo lives at `/Users/server/managebac-mcp` (branch `multi-user`). `uv` is at
`/Users/server/.local/bin/uv` (not on PATH).

## First-time install

```bash
# on the Mac, as the `server` user
cd ~ && git clone -b multi-user https://github.com/levnw/managebac-mcp
cd managebac-mcp && ~/.local/bin/uv sync
```

Then install the two LaunchDaemons (starts them at boot, no desktop login
needed) and disable sleep:

```bash
sudo bash deploy/install-macos-daemons.sh
```

This writes `/Library/LaunchDaemons/com.managebac.{mcp,cloudflared}.plist`,
bootstraps them into the system domain, and sets `pmset` so the Mac never sleeps
(a sleeping Mac drops the tunnel). The MCP daemon runs:

```
managebac-mcp serve --host 127.0.0.1 --port 8000 --public-url https://managebac.822538.xyz
```

`--public-url` is **required** — the OAuth discovery metadata is built from it.

## Deploy an update

```bash
ssh server@100.77.121.118 \
  "cd /Users/server/managebac-mcp && git pull --ff-only origin multi-user && \
   .venv/bin/uv sync && launchctl kickstart -k system/com.managebac.mcp"
```

(If the daemons are running as per-user LaunchAgents in `gui/502` rather than
system daemons, use `launchctl kickstart -k gui/502/com.managebac.mcp`.)

## Health checks

```bash
curl https://managebac.822538.xyz/        # "ManageBac MCP server is running…"
curl https://managebac.822538.xyz/.well-known/oauth-protected-resource   # OAuth discovery JSON
```

Logs: `/tmp/managebac-mcp.log`, `/tmp/cloudflared.log`.

---

## Connecting from ChatGPT

Everyone adds the **same** connector — no per-user URL:

```
https://managebac.822538.xyz/mcp
```

ChatGPT → **Settings → Connectors → Add custom connector** → paste that URL →
create → click **Sign in**. New students enter their school URL, email, password,
and a one-time invite code (generate codes in the admin panel); returning
students just log in. (Requires a ChatGPT plan with custom connectors enabled.)

---

## Managing users

```bash
# in /Users/server/managebac-mcp on the Mac
.venv/bin/managebac-mcp users          # list enrolled users
.venv/bin/managebac-mcp deluser <id>   # remove a user + their cached data
```

Or use the admin panel at `https://managebac.822538.xyz/admin` (invite codes,
pause/resume, messaging).

## Where data lives on the server

Under `/Users/server/.managebac_mcp/`: `users.db` (encrypted credentials),
`oauth.db` (access/refresh tokens), `admin.db` (invite codes, admin sessions),
`secret.key` (encryption key — back this up separately and keep it private), and
`cache.db`.
