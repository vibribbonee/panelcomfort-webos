#!/bin/sh
# Secret-link webhook API. The random token is part of the CGI filename and is not logged.
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
LOG="$ROOT_DIR/service.log"
umask 077
get_lan_ip(){
  ipaddr=''
  if command -v ip >/dev/null 2>&1; then
    ipaddr=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9][0-9.]*\).*/\1/p' | head -n 1)
    case "$ipaddr" in 127.*|'') ipaddr=$(ip -4 addr show 2>/dev/null | sed -n 's/.*inet \([0-9][0-9.]*\)\/.*/\1/p' | grep -v '^127\.' | head -n 1);; esac
  fi
  if [ -z "$ipaddr" ] && command -v ifconfig >/dev/null 2>&1; then ipaddr=$(ifconfig 2>/dev/null | sed -n 's/.*inet addr:\([0-9][0-9.]*\).*/\1/p; s/.*inet \([0-9][0-9.]*\) netmask.*/\1/p' | grep -v '^127\.' | head -n 1); fi
  case "$ipaddr" in *.*.*.*) printf '%s\n' "$ipaddr";; *) return 1;; esac
}
local_client(){
  remote=${REMOTE_ADDR:-}
  case "$remote" in 127.*|10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) return 0;; *) return 1;; esac
}
respond_error(){
  code=$1; msg=$2
  printf 'Status: %s\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n' "$code"
  printf '{"ok":false,"error":"%s"}\n' "$msg"
  exit 0
}
release_config_lock(){ rm -f "$CONFIG_LOCK/pid"; rmdir "$CONFIG_LOCK" 2>/dev/null || true; }
acquire_config_lock(){
  tries=0
  while ! mkdir "$CONFIG_LOCK" 2>/dev/null; do
    owner=$(cat "$CONFIG_LOCK/pid" 2>/dev/null || true)
    case "$owner" in
      ''|*[!0-9]*) ;;
      *)
        if ! kill -0 "$owner" 2>/dev/null; then rm -rf "$CONFIG_LOCK" 2>/dev/null || true
        elif [ -r "/proc/$owner/cmdline" ] && ! tr '\000' ' ' < "/proc/$owner/cmdline" 2>/dev/null | grep -Eq 'panelcomfort-(ha|web)\.cgi|panelcomfort\.cgi|pc-[a-fA-F0-9]{8}'; then rm -rf "$CONFIG_LOCK" 2>/dev/null || true
        fi ;;
    esac
    tries=$((tries + 1))
    [ "$tries" -lt 100 ] || respond_error '503 Service Unavailable' 'settings are busy; retry shortly'
    sleep 0.1
  done
  printf '%s\n' "$$" > "$CONFIG_LOCK/pid"
  trap release_config_lock 0
  trap 'release_config_lock; exit 1' HUP INT TERM
  . "$CFG"
}
[ -r "$CFG" ] || respond_error '503 Service Unavailable' 'PanelComfort is not configured'
. "$CFG"
[ "${WEBHOOK_ENABLED:-0}" = 1 ] || respond_error '404 Not Found' 'PanelComfort webhooks are disabled'
local_client || respond_error '403 Forbidden' 'private IPv4 client required'
CONFIG_LOCK="$ROOT_DIR/config-write.lock"
case "${QUERY_STRING:-}" in action=status) ;; *) acquire_config_lock;; esac
movie_override(){ [ -f "$ROOT_DIR/override.flag" ]; }
apply_now(){ [ -x "$ROOT_DIR/apply-queue.sh" ] && "$ROOT_DIR/apply-queue.sh" || respond_error '503 Service Unavailable' 'could not queue the screen brightness update'; }
valid_lux_stability(){ case "$1" in ''|*[!0-9]*) return 1;; esac; [ "$(printf '%s' "$1" | wc -c | tr -d ' ')" -le 4 ] && [ "$1" -le 1000 ] 2>/dev/null; }
store_lux_sample(){
  incoming=$1; stamp=$(date +%s); stability=${LUX_STABILITY:-10}
  valid_lux_stability "$stability" || stability=10
  previous=${HA_AMBIENT_LUX:-}; previous_stamp=${HA_AMBIENT_LUX_UPDATED:-0}
  case "$previous" in ''|*[!0-9]*) previous='';; esac
  case "$previous_stamp" in ''|*[!0-9]*) previous_stamp=0;; esac
  if [ -n "$previous" ] && [ "$previous" -le 200000 ] 2>/dev/null && [ "$previous_stamp" -gt 0 ] 2>/dev/null && [ "$stamp" -ge "$previous_stamp" ] 2>/dev/null && [ $((stamp-previous_stamp)) -le 180 ] 2>/dev/null; then
    difference=$((incoming - previous)); [ "$difference" -lt 0 ] && difference=$((-difference))
    if [ "$difference" -le "$stability" ] 2>/dev/null; then
      if grep -q '^HA_AMBIENT_LUX_UPDATED=' "$CFG"; then sed "s/^HA_AMBIENT_LUX_UPDATED=.*/HA_AMBIENT_LUX_UPDATED=$stamp/" "$CFG" > "$CFG.tmp.$$" && chmod 600 "$CFG.tmp.$$" && mv "$CFG.tmp.$$" "$CFG" || return 1; else printf 'HA_AMBIENT_LUX_UPDATED=%s\n' "$stamp" >> "$CFG" || return 1; fi
      HA_AMBIENT_LUX_UPDATED=$stamp
      return 2
    fi
  fi
  for pair in "HA_AMBIENT_LUX=$incoming" "HA_AMBIENT_LUX_UPDATED=$stamp"; do
    key=${pair%%=*}; value=${pair#*=}
    if grep -q "^${key}=" "$CFG"; then sed "s/^${key}=.*/${key}=${value}/" "$CFG" > "$CFG.tmp.$$" && mv "$CFG.tmp.$$" "$CFG" || return 1; else printf '%s=%s\n' "$key" "$value" >> "$CFG" || return 1; fi
  done
  chmod 600 "$CFG" || return 1
  HA_AMBIENT_LUX=$incoming; HA_AMBIENT_LUX_UPDATED=$stamp
  return 0
}
case "${QUERY_STRING:-}" in
  movie=on) : > "$ROOT_DIR/override.flag"; apply_now ;;
  movie=off) rm -f "$ROOT_DIR/override.flag"; apply_now ;;
  movie=toggle) if movie_override; then rm -f "$ROOT_DIR/override.flag"; else : > "$ROOT_DIR/override.flag"; fi; apply_now ;;
  ambient_lux=*)
    lux=${QUERY_STRING#ambient_lux=}
    case "$lux" in ''|*[!0-9]*) respond_error '400 Bad Request' 'ambient lux must be an integer from 0 to 200000';; esac
    [ "$(printf '%s' "$lux" | wc -c | tr -d ' ')" -le 6 ] || respond_error '400 Bad Request' 'ambient lux is out of range'
    [ "$lux" -le 200000 ] 2>/dev/null || respond_error '400 Bad Request' 'ambient lux is out of range'
    store_lux_sample "$lux"; lux_rc=$?
    case "$lux_rc" in
      0) apply_now ;;
      2) : ;;
      *) respond_error '500 Internal Server Error' 'could not save lux reading' ;;
    esac ;;
  action=status|status=1) ;;
  *) respond_error '400 Bad Request' 'Use movie=on, movie=off, movie=toggle, ambient_lux=VALUE, or action=status' ;;
esac
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n'
values=$($ROOT_DIR/daemon.sh --calculate 2>/dev/null || echo '0 off unavailable 0')
set -- $values
backlight=${1:-0}; eye=${2:-off}; phase=${3:-unavailable}; hdr_brightness=${4:-0}
case "$backlight" in *[!0-9]*|'') backlight=0;; esac
case "$eye" in on|off) ;; *) eye=off;; esac
case "$hdr_brightness" in *[!0-9]*|'') hdr_brightness=0;; esac
case "$phase" in day|night|evening-fade|morning-fade|solar-fade|ambient-response|tv-sensor-response|movie-override|disabled) ;; *) phase=unavailable;; esac
if movie_override; then override=true; else override=false; fi
if [ "${ENABLED:-1}" = 1 ]; then enabled=true; else enabled=false; fi
if [ "${EYE_ENABLED:-1}" = 1 ]; then eye_schedule=true; else eye_schedule=false; fi
if [ "${HYPERHDR_ENABLED:-0}" = 1 ]; then hdr_enabled=true; else hdr_enabled=false; fi
case "${HA_AMBIENT_LUX:-0}" in ''|*[!0-9]*) lux=0;; *) lux=${HA_AMBIENT_LUX:-0};; esac
case "${HA_AMBIENT_LUX_UPDATED:-0}" in ''|*[!0-9]*) lux_updated=0;; *) lux_updated=${HA_AMBIENT_LUX_UPDATED:-0};; esac
printf '{"ok":true,"device_id":"%s","movie_override":%s,"service_enabled":%s,"eye_comfort":"%s","eye_schedule_enabled":%s,"backlight":%s,"ambient_lux":%s,"ambient_lux_updated":%s,"hyperhdr_enabled":%s,"hyperhdr_brightness":%s,"phase":"%s"}\n' \
  "$HA_DEVICE_ID" "$override" "$enabled" "$eye" "$eye_schedule" "$backlight" "$lux" "$lux_updated" "$hdr_enabled" "$hdr_brightness" "$phase"
