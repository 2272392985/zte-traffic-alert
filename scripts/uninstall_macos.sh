#!/bin/sh
set -eu

PLIST_PATH="$HOME/Library/LaunchAgents/com.local.zte-traffic-alert.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
rm -f "$PLIST_PATH"

echo "Uninstalled com.local.zte-traffic-alert"

