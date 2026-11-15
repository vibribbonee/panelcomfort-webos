#!/bin/sh
# Announce PanelComfort with SSDP so Home Assistant can offer an integration discovery card.
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
LOG="$ROOT_DIR/ssdp.log"
SERVICE='urn:panelcomfort-webos-org:device:PanelComfort:1'
get_lan_ip(){
  ipaddr=''
  if command -v ip >/dev/null 2>&1; then
    ipaddr=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9][0-9.]*\).*/\1/p' | head -n 1)
    case "$ipaddr" in 127.*|'') ipaddr=$(ip -4 addr show 2>/dev/null | sed -n 's/.*inet \([0-9][0-9.]*\)\/.*/\1/p' | grep -v '^127\.' | head -n 1);; esac
  fi
  if [ -z "$ipaddr" ] && command -v ifconfig >/dev/null 2>&1; then ipaddr=$(ifconfig 2>/dev/null | sed -n 's/.*inet addr:\([0-9][0-9.]*\).*/\1/p; s/.*inet \([0-9][0-9.]*\) netmask.*/\1/p' | grep -v '^127\.' | head -n 1); fi
  case "$ipaddr" in *.*.*.*) printf '%s\n' "$ipaddr";; *) return 1;; esac
}
send_notify(){
  ipaddr=$1; port=$2; udn=$3
  if command -v nc >/dev/null 2>&1; then set -- nc; elif busybox --list 2>/dev/null | grep -qx nc; then set -- busybox nc; else return 1; fi
  { printf 'NOTIFY * HTTP/1.1\r\n'; printf 'HOST: 239.255.255.250:1900\r\n'; printf 'CACHE-CONTROL: max-age=180\r\n'; printf 'LOCATION: http://%s:%s/device.xml\r\n' "$ipaddr" "$port"; printf 'NT: %s\r\n' "$SERVICE"; printf 'NTS: ssdp:alive\r\n'; printf 'SERVER: webOS/6 UPnP/1.1 PanelComfort/0.3.20\r\n'; printf 'USN: uuid:%s::%s\r\n' "$udn" "$SERVICE"; printf 'BOOTID.UPNP.ORG: 1\r\n'; printf 'CONFIGID.UPNP.ORG: 1\r\n\r\n'; } | "$@" -u -w 1 239.255.255.250 1900 >/dev/null 2>&1
}
while :; do
  [ -r "$CFG" ] || { sleep 10; continue; }
  . "$CFG"
  if [ "${HA_API_ENABLED:-0}" != 1 ] || [ -z "${HA_DEVICE_ID:-}" ]; then sleep 10; continue; fi
  ipaddr=$(get_lan_ip 2>/dev/null || true)
  if [ -n "$ipaddr" ]; then
    # Convert the stable 96-bit device ID into a syntactically valid UUID.
    # UUID fields must be 8-4-4-4-12; never append the raw ID to a fixed prefix.
    make_udn(){
      _id=$1
      case "$_id" in ''|*[!a-fA-F0-9]*) return 1;; esac
      [ "${#_id}" -eq 24 ] || return 1
      printf '%s-%s-4%s-8%s-%s\n' "$(printf '%s' "$_id" | cut -c1-8)" "$(printf '%s' "$_id" | cut -c9-12)" "$(printf '%s' "$_id" | cut -c13-15)" "$(printf '%s' "$_id" | cut -c16-18)" "$(printf '%s' "$_id" | cut -c13-24)"
    }
    udn=$(make_udn "$HA_DEVICE_ID") || { echo 'ERROR=HA_DEVICE_ID must be 24 hexadecimal characters' >> "$LOG"; exit 1; }
    if ! send_notify "$ipaddr" "${HA_API_PORT:-8765}" "$udn"; then
      if [ ! -f "$ROOT_DIR/ssdp-unavailable-logged" ]; then echo "$(date '+%Y-%m-%d %H:%M:%S') SSDP multicast unavailable (netcat/UDP may not be included); manual Add integration scan remains available" >> "$LOG"; : > "$ROOT_DIR/ssdp-unavailable-logged"; fi
    fi
  fi
  sleep 60
done
