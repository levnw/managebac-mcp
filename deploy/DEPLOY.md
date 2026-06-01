# Deploying the ManageBac MCP server

This sets up the multi-user server on a Linux server and exposes it at
**https://managebac.822538.xyz** through a Cloudflare Tunnel. Your friends then
enroll at `/enroll` and connect from ChatGPT.

Assumes a Debian/Ubuntu server with `systemd`. If you're on something else, the
commands are similar — tell me your OS and I'll adjust.

---

## Overview

```
ChatGPT  ──HTTPS──>  Cloudflare  ──tunnel──>  cloudflared (on your server)
                                                    │
                                                    └─> localhost:8000  (managebac-mcp serve)
```

The MCP server only listens on `localhost` — it's never exposed to the internet
directly. Cloudflare reaches it through the tunnel, so there are no inbound
ports to open on the server's firewall.

---

## 1. Get the code onto the server

```bash
sudo mkdir -p /opt/managebac-mcp
sudo chown "$USER" /opt/managebac-mcp
git clone -b multi-user https://github.com/levnw/managebac-mcp /opt/managebac-mcp
cd /opt/managebac-mcp
```

## 2. Install Python deps with uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh      # if uv isn't installed
cd /opt/managebac-mcp
uv sync
```

Quick check it runs (Ctrl+C to stop):

```bash
.venv/bin/managebac-mcp serve --host 127.0.0.1 --port 8000
```

## 3. Run the server as a service

```bash
# Create a dedicated user to run it
sudo useradd -r -s /usr/sbin/nologin mbmcp || true
sudo chown -R mbmcp /opt/managebac-mcp

# (Optional but recommended) require an invite code to enroll:
#   edit deploy/managebac-mcp.service and uncomment the Environment line
sudo cp deploy/managebac-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now managebac-mcp
sudo systemctl status managebac-mcp        # should be "active (running)"
```

## 4. Install cloudflared

```bash
# Debian/Ubuntu
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb
```

## 5. Log in to Cloudflare (this step is YOURS)

```bash
cloudflared tunnel login
```

This opens a browser. Log into your Cloudflare account and pick the
**822538.xyz** zone. This is the one step that can't be automated — it
authorizes your account.

## 6. Create the tunnel + DNS + service

```bash
sudo bash deploy/setup-tunnel.sh
```

This creates a tunnel named `managebac`, points `managebac.822538.xyz` at it,
writes `/etc/cloudflared/config.yml`, and starts cloudflared as a service.

## 7. Test it

```bash
curl https://managebac.822538.xyz/
# -> "ManageBac MCP server is running. Visit /enroll to connect an account."
```

Open `https://managebac.822538.xyz/enroll` in a browser and connect your own
ManageBac account — you'll get your personal connector URL.

---

## Connecting from ChatGPT

In ChatGPT → **Settings → Connectors → Add custom connector**, paste the URL the
enroll page gave you:

```
https://managebac.822538.xyz/mcp?key=YOUR_TOKEN
```

(Requires a ChatGPT plan with developer mode / custom connectors enabled.)

---

## Updating later

```bash
cd /opt/managebac-mcp
git pull
uv sync
sudo systemctl restart managebac-mcp
```

## Managing users

```bash
sudo -u mbmcp /opt/managebac-mcp/.venv/bin/managebac-mcp users        # list
sudo -u mbmcp /opt/managebac-mcp/.venv/bin/managebac-mcp deluser <id> # remove
```

## Where data lives on the server

Everything is under the `mbmcp` user's home (`~/.managebac_mcp/`):
`users.db` (encrypted credentials), `secret.key` (encryption key — back this up
separately and keep it private), and `cache.db`.
