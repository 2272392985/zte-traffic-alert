#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CONFIG_PATH="$PROJECT_DIR/config.json"
PLIST_PATH="$HOME/Library/LaunchAgents/com.local.zte-traffic-alert.plist"
PYTHON_BIN=$(command -v python3)

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Missing config.json. Copy config.example.json to config.json first."
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.zte-traffic-alert</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>-m</string>
    <string>zte_traffic_alert</string>
    <string>--config</string>
    <string>$CONFIG_PATH</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>$PROJECT_DIR</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_DIR/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/com.local.zte-traffic-alert"

echo "Installed com.local.zte-traffic-alert"
echo "Config: $CONFIG_PATH"
echo "Log: $PROJECT_DIR/zte_traffic_alert.log"

