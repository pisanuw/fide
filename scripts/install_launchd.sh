#!/bin/bash
# Install (or remove) the launchd job that runs scripts/refresh_on_host.sh on
# the 3rd and 8th of each month at 09:17 local time. macOS only.
#
#   scripts/install_launchd.sh            install or update, for the clone this script lives in
#   scripts/install_launchd.sh --remove   uninstall
#
# Log: ~/Library/Logs/fide-refresh.log
set -euo pipefail

LABEL="com.pisanuw.fide-refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/fide-refresh.log"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

# launchd starts jobs with a bare PATH; include Homebrew so python3 is a current one
PATH_FOR_JOB="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/scripts/refresh_on_host.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$PATH_FOR_JOB</string>
  </dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Day</key><integer>3</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>17</integer></dict>
    <dict><key>Day</key><integer>8</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>17</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "installed $LABEL for $REPO"
echo "runs on the 3rd and 8th at 09:17; log: $LOG"
echo "run it now with: launchctl kickstart $DOMAIN/$LABEL"
