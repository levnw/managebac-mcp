#!/usr/bin/env bash
# Creates the Cloudflare tunnel and wires it to managebac.822538.xyz.
#
# Run this ON THE SERVER, AFTER you have run:   cloudflared tunnel login
# (that login step opens a browser and authorizes your Cloudflare account —
#  only you can do it).
#
# Usage:  sudo bash setup-tunnel.sh
set -euo pipefail

HOSTNAME="managebac.822538.xyz"
TUNNEL_NAME="managebac"
CONFIG_DIR="/etc/cloudflared"

if [ ! -f "$HOME/.cloudflared/cert.pem" ] && [ ! -f "/root/.cloudflared/cert.pem" ]; then
  echo "✗ Not logged in to Cloudflare yet."
  echo "  Run:  cloudflared tunnel login"
  echo "  (pick the 822538.xyz zone in the browser), then re-run this script."
  exit 1
fi

echo "==> Creating tunnel '$TUNNEL_NAME' (skips if it already exists)"
cloudflared tunnel create "$TUNNEL_NAME" 2>/dev/null || echo "   (tunnel already exists, continuing)"

# Find the tunnel UUID + its credentials file
TUNNEL_ID=$(cloudflared tunnel list --output json | python3 -c "import sys,json;print(next(t['id'] for t in json.load(sys.stdin) if t['name']=='$TUNNEL_NAME'))")
echo "==> Tunnel ID: $TUNNEL_ID"

echo "==> Routing $HOSTNAME -> tunnel"
cloudflared tunnel route dns "$TUNNEL_NAME" "$HOSTNAME" || echo "   (DNS route may already exist, continuing)"

echo "==> Writing $CONFIG_DIR/config.yml"
mkdir -p "$CONFIG_DIR"
# Move the credentials file into place
CRED_SRC=$(find "$HOME/.cloudflared" /root/.cloudflared -name "$TUNNEL_ID.json" 2>/dev/null | head -1 || true)
if [ -n "$CRED_SRC" ]; then
  cp "$CRED_SRC" "$CONFIG_DIR/$TUNNEL_ID.json"
fi
sed "s/TUNNEL_ID/$TUNNEL_ID/g" "$(dirname "$0")/cloudflared-config.yml" > "$CONFIG_DIR/config.yml"

echo "==> Installing cloudflared as a system service"
cloudflared service install || true
systemctl enable --now cloudflared || true

echo ""
echo "✓ Done. The tunnel is live at: https://$HOSTNAME"
echo "  Test it:   curl https://$HOSTNAME/"
echo "  Enroll at: https://$HOSTNAME/enroll"
