#!/bin/sh
# Public, non-secret discovery endpoint. Never returns the control token.
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
get_lan_ip(){
  ipaddr=''
  if command -v ip >/dev/null 2>&1; then
    ipaddr=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9][0-9.]*\).*/\1/p' | head -n 1)
    case "$ipaddr" in 127.*|'') ipaddr=$(ip -4 addr show 2>/dev/null | sed -n 's/.*inet \([0-9][0-9.]*\)\/.*/\1/p' | grep -v '^127\.' | head -n 1);; esac
  fi
  if [ -z "$ipaddr" ] && command -v ifconfig >/dev/null 2>&1; then ipaddr=$(ifconfig 2>/dev/null | sed -n 's/.*inet addr:\([0-9][0-9.]*\).*/\1/p; s/.*inet \([0-9][0-9.]*\) netmask.*/\1/p' | grep -v '^127\.' | head -n 1); fi
  case "$ipaddr" in *.*.*.*) printf '%s\n' "$ipaddr";; *) return 1;; esac
}
fail(){ code=$1; msg=$2; printf 'Status: %s\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n' "$code"; printf '{"ok":false,"error":"%s"}\n' "$msg"; exit 0; }
[ -r "$CFG" ] || fail '503 Service Unavailable' 'not configured'
. "$CFG"
[ "${HA_API_ENABLED:-0}" = 1 ] || fail '404 Not Found' 'discovery disabled'
remote=${REMOTE_ADDR:-}
case "$remote" in
  127.*|10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) ;;
  *) fail '403 Forbidden' 'private IPv4 client required' ;;
esac
printf '%s' "${HA_DEVICE_ID:-}" | grep -Eq '^[a-fA-F0-9]{24}$' || fail '503 Service Unavailable' 'device ID must be 24 hexadecimal characters'
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n'
printf '{"ok":true,"domain":"panelcomfort","device_id":"%s","port":%s,"version":"0.3.21"}\n' "$HA_DEVICE_ID" "${HA_API_PORT:-8765}"
