#!/bin/sh
# Shared local HTTP listener for the status page plus optional Home Assistant,
# secret-link webhook, and browser-dashboard controls. It only creates files below
# /var/lib/webosbrew.
set -u
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
WEBROOT="$ROOT_DIR/www"
PIDFILE="$ROOT_DIR/httpd.pid"
SSDP_PIDFILE="$ROOT_DIR/ssdp.pid"
LOG="$ROOT_DIR/httpd.log"
APP_ID=com.webosbrew.panelcomfort

valid_pid(){
  p="$1"; pattern="$2"
  case "$p" in ''|*[!0-9]*) return 1;; esac
  [ -r "/proc/$p/cmdline" ] || return 1
  tr '\000' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -q "$pattern"
}
valid_listener_pid(){ valid_pid "$1" 'panelcomfort-httpd.js' || valid_pid "$1" 'httpd.*-f'; }
stop_owned(){
  file=$1; pattern=$2
  if [ -f "$file" ]; then p=$(cat "$file" 2>/dev/null || true); if valid_pid "$p" "$pattern"; then kill "$p" 2>/dev/null || true; fi; rm -f "$file"; fi
}
stop_listener(){
  if [ -f "$PIDFILE" ]; then
    p=$(cat "$PIDFILE" 2>/dev/null || true)
    if valid_listener_pid "$p"; then kill "$p" 2>/dev/null || true; fi
    rm -f "$PIDFILE"
  fi
}
get_lan_ip(){
  ipaddr=''
  if command -v ip >/dev/null 2>&1; then
    ipaddr=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9][0-9.]*\).*/\1/p' | head -n 1)
    case "$ipaddr" in 127.*|'') ipaddr=$(ip -4 addr show 2>/dev/null | sed -n 's/.*inet \([0-9][0-9.]*\)\/.*/\1/p' | grep -v '^127\.' | head -n 1);; esac
  fi
  if [ -z "$ipaddr" ] && command -v ifconfig >/dev/null 2>&1; then ipaddr=$(ifconfig 2>/dev/null | sed -n 's/.*inet addr:\([0-9][0-9.]*\).*/\1/p; s/.*inet \([0-9][0-9.]*\) netmask.*/\1/p' | grep -v '^127\.' | head -n 1); fi
  case "$ipaddr" in *.*.*.*) printf '%s\n' "$ipaddr";; *) return 1;; esac
}
case "${1:-restart}" in
  stop) stop_listener; stop_owned "$SSDP_PIDFILE" 'ssdp-broadcast.sh'; exit 0 ;;
  status)
    if [ -f "$PIDFILE" ] && valid_listener_pid "$(cat "$PIDFILE" 2>/dev/null)"; then echo HTTPD_RUNNING=1; else echo HTTPD_RUNNING=0; fi
    echo HTTPD_EXPECTED=1
    if [ -f "$SSDP_PIDFILE" ] && valid_pid "$(cat "$SSDP_PIDFILE" 2>/dev/null)" 'ssdp-broadcast.sh'; then echo SSDP_RUNNING=1; else echo SSDP_RUNNING=0; fi
    if [ -r "$CFG" ]; then
      . "$CFG"
      printf 'HA_DEVICE_ID=%s\n' "${HA_DEVICE_ID:-}"
      printf 'HA_API_ENABLED=%s\n' "${HA_API_ENABLED:-0}"
      printf 'WEBHOOK_ENABLED=%s\n' "${WEBHOOK_ENABLED:-0}"
      printf 'WEB_UI_ENABLED=%s\n' "${WEB_UI_ENABLED:-0}"
      if [ "${HA_API_ENABLED:-0}" = 1 ] && [ -f "$PIDFILE" ] && valid_listener_pid "$(cat "$PIDFILE" 2>/dev/null)"; then echo HA_API_RUNNING=1; else echo HA_API_RUNNING=0; fi
    else echo HA_API_RUNNING=0; fi
    get_lan_ip 2>/dev/null | sed 's/^/TV_LAN_IP=/' || true
    if [ -r "$ROOT_DIR/profile-status" ]; then printf 'PROFILE_CONTEXT=%s\n' "$(cat "$ROOT_DIR/profile-status")"; fi
    exit 0 ;;
  restart|start) ;;
  *) echo 'ERROR=use start, stop, restart or status'; exit 2 ;;
esac
stop_listener
stop_owned "$SSDP_PIDFILE" 'ssdp-broadcast.sh'
[ -r "$CFG" ] || exit 0
. "$CFG"
ha_enabled=${HA_API_ENABLED:-0}; webhook_enabled=${WEBHOOK_ENABLED:-0}; web_ui_enabled=${WEB_UI_ENABLED:-0}
port=${HA_API_PORT:-8765}
case "$port" in ''|*[!0-9]*) echo 'ERROR=Local control port must be numeric' >> "$LOG"; exit 1;; esac
[ "$port" -ge 1024 ] 2>/dev/null && [ "$port" -le 65535 ] 2>/dev/null || { echo 'ERROR=Local control port must be 1024-65535' >> "$LOG"; exit 1; }
if [ "$ha_enabled" = 1 ] && ! printf '%s' "${HA_DEVICE_ID:-}" | grep -Eq '^[a-fA-F0-9]{24}$'; then
  device_id=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
  if grep -q '^HA_DEVICE_ID=' "$CFG"; then sed "s/^HA_DEVICE_ID=.*/HA_DEVICE_ID=$device_id/" "$CFG" > "$CFG.tmp" && mv "$CFG.tmp" "$CFG"; else printf 'HA_DEVICE_ID=%s\n' "$device_id" >> "$CFG"; fi
  HA_DEVICE_ID=$device_id
fi
if [ "$webhook_enabled" = 1 ] && ! printf '%s' "${WEBHOOK_TOKEN:-}" | grep -Eq '^[a-fA-F0-9]{8}$'; then
  token=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n' | cut -c1-8)
  if grep -q '^WEBHOOK_TOKEN=' "$CFG"; then sed "s/^WEBHOOK_TOKEN=.*/WEBHOOK_TOKEN=$token/" "$CFG" > "$CFG.tmp" && mv "$CFG.tmp" "$CFG"; else printf 'WEBHOOK_TOKEN=%s\n' "$token" >> "$CFG"; fi
  WEBHOOK_TOKEN=$token
fi
lan_ip=$(get_lan_ip 2>/dev/null || true)
[ -n "$lan_ip" ] || echo 'WARNING=Could not detect the TV LAN IP; listener still binds 0.0.0.0' >> "$LOG"
mkdir -p "$WEBROOT/cgi-bin"
cat > "$WEBROOT/cgi-bin/index.cgi" <<'CGI'
#!/bin/sh
printf 'Status: 404 Not Found\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n{"ok":false,"error":"Use the PanelComfort integration endpoint."}\n'
CGI
chmod 755 "$WEBROOT/cgi-bin/index.cgi"
cp "$ROOT_DIR/panelcomfort-health.cgi" "$WEBROOT/cgi-bin/panelcomfort-health.cgi"
chmod 755 "$WEBROOT/cgi-bin/panelcomfort-health.cgi"
rm -f "$WEBROOT/cgi-bin/pc-"*
cat > "$WEBROOT/index.html" <<'HTML'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>PanelComfort · TV service</title>
  <style>
    :root{color-scheme:dark;font:16px/1.6 system-ui,sans-serif;background:#10131b;color:#f3f5fa}
    body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;box-sizing:border-box}
    main{width:min(100%,620px);padding:28px;border:1px solid #343b4e;border-radius:18px;background:#191e29;box-sizing:border-box}
    h1{margin:0 0 8px;font-size:1.8rem}p{color:#bdc5d7}a{color:#9bc8ff}
    li{margin:.5rem 0}code{overflow-wrap:anywhere}
  </style>
</head>
<body>
  <main>
    <h1>PanelComfort is running</h1>
    <p>This status page is available on your local network. Enable Home Assistant or webhook controls separately in the TV app. Enabling the optional browser dashboard replaces this page with the control dashboard. HyperHDR has a separate control page, usually on port 8090.</p>
    <ul>
      <li><a href="/cgi-bin/panelcomfort-health.cgi">Check service health</a></li>
HTML
if [ "$ha_enabled" = 1 ]; then
  printf '      <li><a href="/cgi-bin/panelcomfort-discovery.cgi">Home Assistant discovery endpoint</a></li>\n' >> "$WEBROOT/index.html"
else
  printf '      <li>Home Assistant discovery is disabled in the TV app.</li>\n' >> "$WEBROOT/index.html"
fi
if [ "$webhook_enabled" = 1 ]; then
  printf '      <li>Webhooks are enabled. Open the Webhooks section in the TV app to copy the private URL.</li>\n' >> "$WEBROOT/index.html"
else
  printf '      <li>Webhooks are disabled in the TV app.</li>\n' >> "$WEBROOT/index.html"
fi
cat >> "$WEBROOT/index.html" <<'HTML'
    </ul>
    <p>For brightness schedules, sensor settings, and Movie Mode, open the PanelComfort app on the TV.</p>
  </main>
</body>
</html>
HTML
chmod 644 "$WEBROOT/index.html"
if [ "$web_ui_enabled" = 1 ]; then
  mkdir -p "$ROOT_DIR/web-ui"
  [ -r "$ROOT_DIR/web-ui/index.html" ] && cp -R "$ROOT_DIR/web-ui/." "$WEBROOT/"
  cp "$ROOT_DIR/panelcomfort-web.cgi" "$WEBROOT/cgi-bin/panelcomfort-web.cgi"
  chmod 755 "$WEBROOT/cgi-bin/panelcomfort-web.cgi"
else
  rm -f "$WEBROOT/panelcomfort.css" "$WEBROOT/panelcomfort.js" "$WEBROOT/cgi-bin/panelcomfort-web.cgi"
fi
if [ "$ha_enabled" = 1 ]; then
  cp "$ROOT_DIR/panelcomfort-ha.cgi" "$WEBROOT/cgi-bin/panelcomfort-ha.cgi"
  cp "$ROOT_DIR/panelcomfort-discovery.cgi" "$WEBROOT/cgi-bin/panelcomfort-discovery.cgi"
  chmod 755 "$WEBROOT/cgi-bin/panelcomfort-ha.cgi" "$WEBROOT/cgi-bin/panelcomfort-discovery.cgi"
  # UPnP UUID uses the stable 12-byte TV ID in a syntactically UUID-shaped value.
  # Convert the stable 96-bit device ID into a syntactically valid UUID.
  # UUID field lengths must be 8-4-4-4-12; appending all 24 hex chars to a
  # fixed prefix creates an invalid 36+ character UUID and breaks SSDP clients.
  make_udn(){
    _id=$1
    case "$_id" in ''|*[!a-fA-F0-9]*) return 1;; esac
    [ "${#_id}" -eq 24 ] || return 1
    printf '%s-%s-4%s-8%s-%s\n' "$(printf '%s' "$_id" | cut -c1-8)" "$(printf '%s' "$_id" | cut -c9-12)" "$(printf '%s' "$_id" | cut -c13-15)" "$(printf '%s' "$_id" | cut -c16-18)" "$(printf '%s' "$_id" | cut -c13-24)"
  }
  udn=$(make_udn "$HA_DEVICE_ID") || { echo 'ERROR=HA_DEVICE_ID must be 24 hexadecimal characters' >> "$LOG"; exit 1; }
  cat > "$WEBROOT/device.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><specVersion><major>1</major><minor>0</minor></specVersion><device><deviceType>urn:panelcomfort-webos-org:device:PanelComfort:1</deviceType><friendlyName>PanelComfort LG webOS TV</friendlyName><manufacturer>PanelComfort</manufacturer><modelName>LG webOS panel scheduler</modelName><UDN>uuid:${udn}</UDN></device></root>
XML
else
  rm -f "$WEBROOT/cgi-bin/panelcomfort-ha.cgi" "$WEBROOT/cgi-bin/panelcomfort-discovery.cgi" "$WEBROOT/device.xml"
fi
if [ "$webhook_enabled" = 1 ]; then cp "$ROOT_DIR/panelcomfort.cgi" "$WEBROOT/cgi-bin/pc-${WEBHOOK_TOKEN}"; chmod 755 "$WEBROOT/cgi-bin/pc-${WEBHOOK_TOKEN}"; fi
node_bin=/usr/bin/node
if [ ! -x "$node_bin" ]; then node_bin=$(command -v node 2>/dev/null || true); fi
if [ -z "$node_bin" ] || [ ! -x "$node_bin" ]; then
  echo 'ERROR=Node.js runtime not found; HTTP listener cannot start' >> "$LOG"
  exit 1
fi
if [ ! -r "$ROOT_DIR/panelcomfort-httpd.js" ]; then
  echo 'ERROR=PanelComfort Node HTTP server script is missing; update the root service' >> "$LOG"
  exit 1
fi
printf '%s Starting PanelComfort Node HTTP server on port %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$port" >> "$LOG"
nohup "$node_bin" "$ROOT_DIR/panelcomfort-httpd.js" "$port" "$WEBROOT" >> "$LOG" 2>&1 &
p=$!
echo "$p" > "$PIDFILE"
sleep 1
if ! valid_pid "$p" 'panelcomfort-httpd.js'; then
  rm -f "$PIDFILE"
  echo 'ERROR=PanelComfort Node HTTP server did not stay running; see httpd.log' >> "$LOG"
  exit 1
fi
if [ "$ha_enabled" = 1 ] && [ -x "$ROOT_DIR/ssdp-broadcast.sh" ]; then
  nohup "$ROOT_DIR/ssdp-broadcast.sh" >/tmp/panelcomfort-ssdp.log 2>&1 &
  echo $! > "$SSDP_PIDFILE"
fi
printf '%s listener running on 0.0.0.0:%s (HA=%s, webhooks=%s, web_ui=%s); private-network checks enabled for control\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$port" "$ha_enabled" "$webhook_enabled" "$web_ui_enabled" >> "$LOG"
exit 0
