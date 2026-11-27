#!/bin/sh
# Local HyperHDR v22 output-scale integration. Applies output scale per selected running instance.
set -u
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
LOG="$ROOT_DIR/service.log"
[ -r "$CFG" ] || { echo 'ERROR=PanelComfort config is missing'; exit 1; }
. "$CFG"

host=${HYPERHDR_HOST:-127.0.0.1}
port_cfg=${HYPERHDR_PORT:-auto}
token=${HYPERHDR_TOKEN:-}

valid_host(){ case "$1" in ''|*[!A-Za-z0-9.-]*) return 1;; esac; return 0; }
valid_host "$host" || { echo 'ERROR=Host must be a hostname or IPv4 address'; exit 1; }
case "$port_cfg" in auto) ;; *[!0-9]*|'') echo 'ERROR=Port must be auto or a number'; exit 1;; *) [ "$port_cfg" -ge 1 ] 2>/dev/null && [ "$port_cfg" -le 65535 ] 2>/dev/null || { echo 'ERROR=Port is out of range'; exit 1; };; esac
case "$token" in *[!A-Za-z0-9._-]*) echo 'ERROR=HyperHDR token contains unsupported characters'; exit 1;; esac

request_info='{"command":"serverinfo"}'
HPORT=''
HRESP=''

post_json(){
  _host=$1 _port=$2 _body=$3
  _url="http://$_host:$_port/json-rpc"
  if command -v curl >/dev/null 2>&1; then
    if [ -n "$token" ]; then
      curl -sS --connect-timeout 0.5 --max-time 1 -H 'Content-Type: application/json' -H "Authorization: Bearer $token" --data "$_body" "$_url" 2>/dev/null
    else
      curl -sS --connect-timeout 0.5 --max-time 1 -H 'Content-Type: application/json' --data "$_body" "$_url" 2>/dev/null
    fi
    return $?
  fi
  if command -v busybox >/dev/null 2>&1; then
    if [ -n "$token" ]; then
      busybox wget -q -O - -T 1 --header='Content-Type: application/json' --header="Authorization: Bearer $token" --post-data="$_body" "$_url" 2>/dev/null
    else
      busybox wget -q -O - -T 1 --header='Content-Type: application/json' --post-data="$_body" "$_url" 2>/dev/null
    fi
    return $?
  fi
  if command -v wget >/dev/null 2>&1; then
    if [ -n "$token" ]; then
      wget -q -O - -T 1 --header='Content-Type: application/json' --header="Authorization: Bearer $token" --post-data="$_body" "$_url" 2>/dev/null
    else
      wget -q -O - -T 1 --header='Content-Type: application/json' --post-data="$_body" "$_url" 2>/dev/null
    fi
    return $?
  fi
  return 127
}

urlencode(){
  # URL-encode a UTF-8/ASCII string without requiring Python or jq. HyperHDR's
  # HTTP JSON-RPC endpoint accepts repeated `request=` query parameters, which
  # share one API session so an instance switch can be followed by a command.
  printf '%s' "$1" | od -An -v -tu1 | awk '{
    for (i=1; i<=NF; i++) {
      n=$i+0
      if ((n>=48 && n<=57) || (n>=65 && n<=90) || (n>=97 && n<=122) || n==45 || n==46 || n==95 || n==126)
        printf "%c", n
      else
        printf "%%%02X", n
    }
  }'
}

post_instance_adjustment(){
  _host=$1 _port=$2 _instance=$3 _scale=$4
  _switch="{\"command\":\"instance\",\"subcommand\":\"switchTo\",\"instance\":$_instance}"
  _adjust="{\"command\":\"adjustment\",\"adjustment\":{\"scaleOutput\":$_scale}}"
  _url="http://$_host:$_port/json-rpc?request=$(urlencode "$_switch")&request=$(urlencode "$_adjust")"
  if command -v curl >/dev/null 2>&1; then
    if [ -n "$token" ]; then
      curl -sS --connect-timeout 0.5 --max-time 2 -H "Authorization: Bearer $token" "$_url" 2>/dev/null
    else
      curl -sS --connect-timeout 0.5 --max-time 2 "$_url" 2>/dev/null
    fi
    return $?
  fi
  if command -v busybox >/dev/null 2>&1; then
    if [ -n "$token" ]; then
      busybox wget -q -O - -T 2 --header="Authorization: Bearer $token" "$_url" 2>/dev/null
    else
      busybox wget -q -O - -T 2 "$_url" 2>/dev/null
    fi
    return $?
  fi
  if command -v wget >/dev/null 2>&1; then
    if [ -n "$token" ]; then
      wget -q -O - -T 2 --header="Authorization: Bearer $token" "$_url" 2>/dev/null
    else
      wget -q -O - -T 2 "$_url" 2>/dev/null
    fi
    return $?
  fi
  return 127
}

is_server_info(){
  # HyperHDR serverinfo responses expose an "info" object and success=true;
  # they do not echo the command name in the response.
  printf '%s' "$1" | grep -Eq '\"success\"[[:space:]]*:[[:space:]]*true' &&
  printf '%s' "$1" | grep -Eq '\"info\"[[:space:]]*:'
}
HFAIL='No response from HyperHDR JSON-RPC'
probe_port(){
  _host=$1; _p=$2
  _resp=$(post_json "$_host" "$_p" "$request_info" 2>/dev/null) || {
    HFAIL="Could not POST to $_host:$_p/json-rpc (check host, port and local network access)"; return 1;
  }
  if [ -z "$_resp" ]; then
    HFAIL="No response from $_host:$_p/json-rpc"; return 1
  fi
  if ! is_server_info "$_resp"; then
    if printf '%s' "$_resp" | grep -Eq '\"success\"[[:space:]]*:[[:space:]]*false'; then
      HFAIL="HyperHDR replied with success=false at $_host:$_p; check API token or HyperHDR logs"
    else
      HFAIL="Received a response from $_host:$_p but it was not a successful HyperHDR serverinfo reply"
    fi
    return 1
  fi
  HPORT=$_p; HHOST=$_host; HRESP=$_resp
  if [ "$_host" = 127.0.0.1 ] || [ "$_host" = localhost ]; then
    printf '%s\n' "$_p" > "$ROOT_DIR/hyperhdr.port" 2>/dev/null || true
  fi
  return 0
}

listener_ports(){
  # Read listening TCP ports directly. Parse /proc/net/tcp by whitespace first;
  # splitting the file on ':' loses the column boundaries and misses the port.
  # Try ports nearest to HyperHDR's usual HTTP port first and cap probing so an
  # unavailable service cannot stall the scheduler by scanning every listener.
  for _file in /proc/net/tcp /proc/net/tcp6; do
    [ -r "$_file" ] || continue
    awk '
      function hexval(s, i,n,c) {
        n=0; s=tolower(s); gsub(/[[:space:]]/, "", s)
        for (i=1; i<=length(s); i++) { c=substr(s,i,1); n=n*16+index("0123456789abcdef",c)-1 }
        return n
      }
      NR>1 && $4=="0A" {
        split($2, local, ":"); p=hexval(local[2]);
        if (p>=1024 && p<=65535) print p
      }
    ' "$_file" 2>/dev/null
  done | sort -nu | awk '{d=$1-8090; if(d<0)d=-d; print d, $1}' | sort -n -k1,1 -k2,2n | awk 'NR<=8 {print $2}'
}
get_lan_ip(){
  _ip=''
  if command -v ip >/dev/null 2>&1; then
    _ip=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9][0-9.]*\).*/\1/p' | head -n 1)
    case "$_ip" in 127.*|'') _ip=$(ip -4 addr show 2>/dev/null | sed -n 's/.*inet \([0-9][0-9.]*\)\/.*/\1/p' | grep -v '^127\.' | head -n 1);; esac
  fi
  if [ -z "$_ip" ] && command -v ifconfig >/dev/null 2>&1; then
    _ip=$(ifconfig 2>/dev/null | sed -n 's/.*inet addr:\([0-9][0-9.]*\).*/\1/p; s/.*inet \([0-9][0-9.]*\) netmask.*/\1/p' | grep -v '^127\.' | head -n 1)
  fi
  case "$_ip" in *.*.*.*) printf '%s\n' "$_ip";; *) return 1;; esac
}
find_api(){
  _configured_host=$host
  HPORT=''; HHOST=$host; HRESP=''
  if [ "$port_cfg" != auto ]; then
    if probe_port "$host" "$port_cfg"; then host=$HHOST; return 0; fi
    if [ "$host" = 127.0.0.1 ] || [ "$host" = localhost ]; then
      _lan=$(get_lan_ip 2>/dev/null || true)
      if [ -n "$_lan" ] && [ "$_lan" != "$host" ] && probe_port "$_lan" "$port_cfg"; then host=$HHOST; return 0; fi
    fi
    host=$_configured_host
    return 1
  fi
  if probe_port "$host" 8090; then host=$HHOST; return 0; fi
  if [ "$host" = 127.0.0.1 ] || [ "$host" = localhost ]; then
    _cached=$(cat "$ROOT_DIR/hyperhdr.port" 2>/dev/null || true)
    case "$_cached" in ''|*[!0-9]*|8090) ;; *) if probe_port "$host" "$_cached"; then host=$HHOST; return 0; fi;; esac
    for _p in $(listener_ports); do
      [ -n "$_p" ] || continue; [ "$_p" = 8090 ] && continue; [ "$_p" = "$_cached" ] && continue
      if probe_port "$host" "$_p"; then host=$HHOST; return 0; fi
    done
    # Some rooted-app layouts allow the web UI via the LAN address but not loopback.
    _lan=$(get_lan_ip 2>/dev/null || true)
    if [ -n "$_lan" ] && [ "$_lan" != "$host" ]; then
      if probe_port "$_lan" 8090; then host=$HHOST; return 0; fi
      for _p in $(listener_ports); do
        [ -n "$_p" ] || continue; [ "$_p" = 8090 ] && continue; [ "$_p" = "$_cached" ] && continue
        if probe_port "$_lan" "$_p"; then host=$HHOST; return 0; fi
      done
    fi
  else
    if probe_port "$host" 8090; then host=$HHOST; return 0; fi
  fi
  host=$_configured_host
  return 1
}

extract_running_ids(){
  # Compact JSON before splitting at object braces. HyperHDR may pretty-print
  # serverinfo, so whitespace must be removed first or the instance ID and its
  # running flag can land on different lines.
  printf '%s' "$1" | tr -d '[:space:]' | tr '{' '\n' | tr '}' '\n' |
    awk '
      /"instance":[0-9]+/ && /"running":true/ {
        value=$0; sub(/^.*"instance":/, "", value); sub(/[^0-9].*$/, "", value);
        if (value ~ /^[0-9]+$/ && !seen[value]++) {
          printf "%s%s", sep, value; sep=",";
        }
      }
      END { print "" }
    '
}
case "${1:-test}" in
  test)
    if ! find_api; then
      echo 'HYPERHDR_OK=0'
      printf 'ERROR=%s\n' "$HFAIL"
      exit 1
    fi
    _ids=$(extract_running_ids "$HRESP")
    _count=0
    [ -n "$_ids" ] && _count=$(printf '%s\n' "$_ids" | awk -F, '{print NF}')
    printf 'HYPERHDR_OK=1\nHYPERHDR_HOST=%s\nHYPERHDR_PORT=%s\nHYPERHDR_INSTANCE_IDS=%s\nHYPERHDR_INSTANCE_COUNT=%s\n' "$HHOST" "$HPORT" "$_ids" "$_count"
    exit 0
    ;;
  apply)
    _brightness=${2:-0}
    case "$_brightness" in ''|*[!0-9]*) echo 'ERROR=Brightness must be an integer'; exit 1;; esac
    [ "$_brightness" -le 100 ] 2>/dev/null || _brightness=100
    if ! find_api; then
      printf '%s HyperHDR unavailable (host=%s port=%s)\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$host" "$port_cfg" >> "$LOG"
      exit 1
    fi
    # HyperHDR's HTTP API does not select an instance from an `instance` field
    # on an adjustment command. Switch the API session first, then adjust in
    # that same HTTP request using repeated `request=` parameters.
    _scale=$(awk -v p="$_brightness" 'BEGIN { printf "%.4f", p / 100 }')
    _detected=$(extract_running_ids "$HRESP")
    _configured=${HYPERHDR_INSTANCE_IDS:-all}
    case "$_configured" in
      all) [ -n "$_detected" ] || { echo 'ERROR=Connected to HyperHDR, but could not read its running instance IDs. Enter explicit IDs (for example 0,3), then test and save.'; exit 1; }; _targets=$_detected ;;
      *[!0-9,]*|'') echo 'ERROR=Instances must be all or comma-separated numeric IDs'; exit 1 ;;
      *) _targets=$_configured ;;
    esac
    _failed=0; _summary=''; _oldifs=$IFS; IFS=,
    for _id in $_targets; do
      [ -n "$_id" ] || { _failed=1; _summary="$_summary empty instance ID;"; continue; }
      case ",$_detected," in *,"$_id",*) ;; *) _failed=1; _summary="$_summary instance $_id is not running (detected $_detected);"; continue;; esac
      _one_result=$(post_instance_adjustment "$host" "$HPORT" "$_id" "$_scale" 2>/dev/null) || _one_result=''
      if ! printf '%s' "$_one_result" | grep -Eq '\"success\"[[:space:]]*:[[:space:]]*true'; then
        _failed=1
        _summary="$_summary instance $_id switch failed (response=$_one_result);"
        continue
      fi
      _summary="$_summary instance $_id switched and adjustment sent;"
    done
    IFS=$_oldifs
    if [ "$_failed" -ne 0 ]; then
      printf '%s HyperHDR scaleOutput failed at %s:%s requested=%s%% scaleOutput=%s instances=%s details=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$host" "$HPORT" "$_brightness" "$_scale" "$_targets" "$_summary" >> "$LOG"
      printf 'ERROR=HyperHDR could not switch to every selected instance: %s\n' "$_summary"
      exit 1
    fi
    printf '%s HyperHDR scaleOutput=%s requested=%s%% host=%s port=%s instances=%s details=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$_scale" "$_brightness" "$host" "$HPORT" "$_targets" "$_summary" >> "$LOG"
    printf 'HYPERHDR_APPLY_OK=1\nHYPERHDR_TARGETED_BRIGHTNESS=%s\nHYPERHDR_TARGETED_INSTANCES=%s\n' "$_brightness" "$_targets"
    exit 0
    ;;
  check)
    # Cheap reset watch: a fresh API session reports instance 0. A HyperHDR
    # restart puts every instance back to its saved scale, so when instance 0
    # is targeted and no longer holds the expected value, the caller re-applies.
    # Exit 0 = matches or cannot tell, 1 = HyperHDR was reset.
    _brightness=${2:-}
    case "$_brightness" in ''|*[!0-9]*) exit 0;; esac
    [ "$_brightness" -le 100 ] 2>/dev/null || _brightness=100
    find_api || exit 0
    _configured=${HYPERHDR_INSTANCE_IDS:-all}
    case "$_configured" in all) _targets=$(extract_running_ids "$HRESP");; *) _targets=$_configured;; esac
    case ",$_targets," in *,0,*) ;; *) exit 0;; esac
    _current=$(printf '%s' "$HRESP" | tr -d '[:space:]' | sed -n 's/.*"scaleOutput":\([0-9.]*\).*/\1/p' | head -n 1)
    [ -n "$_current" ] || exit 0
    if awk -v c="$_current" -v p="$_brightness" 'BEGIN { d=c-p/100; if(d<0)d=-d; exit !(d>0.005) }'; then
      printf '%s HyperHDR scaleOutput is %s but should be %s%%; HyperHDR was probably restarted\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$_current" "$_brightness" >> "$LOG"
      exit 1
    fi
    exit 0
    ;;
  *) echo 'ERROR=Use test, apply or check brightness'; exit 2 ;;
esac
