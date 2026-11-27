#!/bin/sh
# Health endpoint works even when the Home Assistant API is disabled.
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
remote=${REMOTE_ADDR:-}
case "$remote" in 127.*|10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) ;; *) printf 'Status: 403 Forbidden\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n{"ok":false,"error":"private IPv4 client required"}\n'; exit 0;; esac
[ -r "$CFG" ] || { printf 'Status: 503 Service Unavailable\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n{"ok":false,"error":"PanelComfort is not configured"}\n'; exit 0; }
. "$CFG"
port=${HA_API_PORT:-8765}; case "$port" in ''|*[!0-9]*) port=8765;; esac
ha=false; hooks=false; web=false
[ "${HA_API_ENABLED:-0}" = 1 ] && ha=true
[ "${WEBHOOK_ENABLED:-0}" = 1 ] && hooks=true
[ "${WEB_UI_ENABLED:-0}" = 1 ] && web=true
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n'
printf '{"ok":true,"domain":"panelcomfort-health","version":"0.3.21","port":%s,"ha_api_enabled":%s,"webhooks_enabled":%s,"web_ui_enabled":%s}\n' "$port" "$ha" "$hooks" "$web"
