#!/usr/bin/env bash
# Convert the ManageBac MCP launchd USER agents into system LaunchDaemons, so a
# headless Mac runs them at boot WITHOUT anyone logging into the desktop.
#
# Run on the server with:   sudo bash install-macos-daemons.sh
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Please run with sudo:  sudo bash $0"
  exit 1
fi

TARGET_USER="server"
TUID="$(id -u "$TARGET_USER")"
SIGNUP_CODE="5f9f8cef"
MCP_BIN="/Users/server/managebac-mcp/.venv/bin/managebac-mcp"
CF_BIN="/opt/homebrew/bin/cloudflared"
CF_CONFIG="/Users/server/.cloudflared/config.yml"

echo "==> Stopping per-user LaunchAgents (if loaded) and removing them"
launchctl bootout "gui/$TUID/com.managebac.mcp" 2>/dev/null || true
launchctl bootout "gui/$TUID/com.managebac.cloudflared" 2>/dev/null || true
sudo -u "$TARGET_USER" rm -f \
  "/Users/$TARGET_USER/Library/LaunchAgents/com.managebac.mcp.plist" \
  "/Users/$TARGET_USER/Library/LaunchAgents/com.managebac.cloudflared.plist"

echo "==> Writing /Library/LaunchDaemons/com.managebac.mcp.plist"
cat > /Library/LaunchDaemons/com.managebac.mcp.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.managebac.mcp</string>
  <key>UserName</key><string>$TARGET_USER</string>
  <key>ProgramArguments</key><array>
    <string>$MCP_BIN</string>
    <string>serve</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8000</string>
    <string>--public-url</string><string>https://managebac.822538.xyz</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/server/managebac-mcp</string>
  <key>EnvironmentVariables</key><dict>
    <key>HOME</key><string>/Users/server</string>
    <key>MANAGEBAC_SIGNUP_CODE</key><string>$SIGNUP_CODE</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/managebac-mcp.log</string>
  <key>StandardErrorPath</key><string>/tmp/managebac-mcp.log</string>
</dict></plist>
PLIST

echo "==> Writing /Library/LaunchDaemons/com.managebac.cloudflared.plist"
cat > /Library/LaunchDaemons/com.managebac.cloudflared.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.managebac.cloudflared</string>
  <key>UserName</key><string>$TARGET_USER</string>
  <key>ProgramArguments</key><array>
    <string>$CF_BIN</string>
    <string>tunnel</string><string>--config</string><string>$CF_CONFIG</string>
    <string>run</string><string>genesis</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>HOME</key><string>/Users/server</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/cloudflared.log</string>
  <key>StandardErrorPath</key><string>/tmp/cloudflared.log</string>
</dict></plist>
PLIST

echo "==> Setting permissions (root:wheel 644)"
chown root:wheel /Library/LaunchDaemons/com.managebac.mcp.plist \
                 /Library/LaunchDaemons/com.managebac.cloudflared.plist
chmod 644 /Library/LaunchDaemons/com.managebac.mcp.plist \
          /Library/LaunchDaemons/com.managebac.cloudflared.plist

echo "==> Loading daemons into the system domain"
launchctl bootout system/com.managebac.mcp 2>/dev/null || true
launchctl bootout system/com.managebac.cloudflared 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/com.managebac.mcp.plist
launchctl bootstrap system /Library/LaunchDaemons/com.managebac.cloudflared.plist
launchctl enable system/com.managebac.mcp
launchctl enable system/com.managebac.cloudflared

echo "==> Power settings for a headless always-on server"
# Never sleep (a sleeping Mac drops the tunnel), and come back after a power cut.
pmset -a sleep 0 2>/dev/null || true
pmset -a disablesleep 1 2>/dev/null || true
pmset -a autorestart 1 2>/dev/null || true
pmset -a womp 1 2>/dev/null || true

sleep 6
echo ""
echo "==> Status"
launchctl print system/com.managebac.mcp 2>/dev/null | grep -E "state =" || echo "  mcp: (check /tmp/managebac-mcp.log)"
launchctl print system/com.managebac.cloudflared 2>/dev/null | grep -E "state =" || echo "  cloudflared: (check /tmp/cloudflared.log)"
echo "==> Local health check"
curl -s --max-time 5 localhost:8000/ || echo "  (not responding yet)"
echo ""
echo "Done. Both services now start at boot, no desktop login required."
