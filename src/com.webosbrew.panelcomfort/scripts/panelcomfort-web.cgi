#!/bin/sh
# Browser dashboard API. Enabled only when WEB_UI_ENABLED=1; accepts private IPv4 clients (not strict same-/24 authentication).
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
LOG="$ROOT_DIR/service.log"
umask 077

json_error(){ code="$1"; msg="$2"; printf 'Status: %s\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n' "$code"; printf '{"ok":false,"error":"%s"}\n' "$msg"; exit 0; }
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
release_config_lock(){ rm -f "$CONFIG_LOCK/pid"; rmdir "$CONFIG_LOCK" 2>/dev/null || true; }
acquire_config_lock(){
  tries=0
  while ! mkdir "$CONFIG_LOCK" 2>/dev/null; do
    owner=$(cat "$CONFIG_LOCK/pid" 2>/dev/null || true)
    case "$owner" in
      ''|*[!0-9]*) ;;
      *)
        if ! kill -0 "$owner" 2>/dev/null; then rm -rf "$CONFIG_LOCK" 2>/dev/null || true
        elif [ -r "/proc/$owner/cmdline" ] && ! tr '\000' ' ' < "/proc/$owner/cmdline" 2>/dev/null | grep -Eq 'panelcomfort-(ha|web)\.cgi'; then rm -rf "$CONFIG_LOCK" 2>/dev/null || true
        fi ;;
    esac
    tries=$((tries + 1))
    [ "$tries" -lt 100 ] || json_error '503 Service Unavailable' 'settings are busy; retry shortly'
    sleep 0.1
  done
  printf '%s\n' "$$" > "$CONFIG_LOCK/pid"
  trap release_config_lock 0
  trap 'release_config_lock; exit 1' HUP INT TERM
  . "$CFG"
}
[ -r "$CFG" ] || json_error '503 Service Unavailable' 'PanelComfort is not configured'
. "$CFG"
[ "${WEB_UI_ENABLED:-0}" = 1 ] || json_error '404 Not Found' 'Browser dashboard is disabled'
local_client || json_error '403 Forbidden' 'private IPv4 client required'

# For browser writes, reject cross-origin web forms/fetches. Non-browser local clients may omit Origin.
if [ "${REQUEST_METHOD:-GET}" = POST ] && [ -n "${HTTP_ORIGIN:-}" ]; then
  expected="http://${HTTP_HOST:-}"
  [ "$HTTP_ORIGIN" = "$expected" ] || json_error '403 Forbidden' 'same-origin request required'
fi

FORM_BODY=''
if [ "${REQUEST_METHOD:-GET}" = POST ]; then
  len=${CONTENT_LENGTH:-0}
  case "$len" in ''|*[!0-9]*) json_error '400 Bad Request' 'invalid content length';; esac
  [ "$len" -le 8192 ] 2>/dev/null || json_error '413 Payload Too Large' 'request too large'
  FORM_BODY=$(dd bs=1 count="$len" 2>/dev/null || true)
elif [ -n "${QUERY_STRING:-}" ] && [ "${QUERY_STRING}" != 'action=status' ]; then
  json_error '405 Method Not Allowed' 'changes must use POST'
fi
CONFIG_LOCK="$ROOT_DIR/config-write.lock"
if [ "${REQUEST_METHOD:-GET}" = POST ]; then acquire_config_lock; fi
param(){ printf '%s\n' "$FORM_BODY" | tr '&' '\n' | sed -n "s/^$1=//p" | head -n 1 | sed -e 's/%3[Aa]/:/g' -e 's/%2[Dd]/-/g' -e 's/%2[Ee]/./g' -e 's/%2[Bb]/+/g' -e 's/+/ /g'; }
valid_int(){ printf '%s' "$1" | grep -Eq '^-?[0-9]{1,5}$'; }
valid_lux_bound(){ printf '%s' "$1" | grep -Eq '^[0-9]{1,6}$' && [ "$1" -le 200000 ] 2>/dev/null; }
valid_lux_stability(){ printf '%s' "$1" | grep -Eq '^[0-9]{1,4}$' && [ "$1" -le 1000 ] 2>/dev/null; }
valid_time(){ case "$1" in [01][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]) return 0;; *) return 1;; esac; }
set_cfg(){
  key=$1; value=$2
  # Keys are literal allow-listed identifiers, and values are validated before this function is called.
  if grep -q "^${key}=" "$CFG"; then
    sed "s/^${key}=.*/${key}=${value}/" "$CFG" > "$CFG.tmp.$$" && chmod 600 "$CFG.tmp.$$" && mv "$CFG.tmp.$$" "$CFG" || return 1
  else printf '%s=%s\n' "$key" "$value" >> "$CFG" || return 1; fi
  chmod 600 "$CFG" || return 1
}
store_lux_sample(){
  incoming=$1; stamp=$(date +%s); stability=${LUX_STABILITY:-10}
  valid_lux_stability "$stability" || stability=10
  previous=${HA_AMBIENT_LUX:-}; previous_stamp=${HA_AMBIENT_LUX_UPDATED:-0}
  case "$previous" in ''|*[!0-9]*) previous='';; esac
  case "$previous_stamp" in ''|*[!0-9]*) previous_stamp=0;; esac
  if [ -n "$previous" ] && [ "$previous" -le 200000 ] 2>/dev/null && [ "$previous_stamp" -gt 0 ] 2>/dev/null && [ "$stamp" -ge "$previous_stamp" ] 2>/dev/null && [ $((stamp-previous_stamp)) -le 180 ] 2>/dev/null; then
    difference=$((incoming - previous)); [ "$difference" -lt 0 ] && difference=$((-difference))
    if [ "$difference" -le "$stability" ] 2>/dev/null; then
      set_cfg HA_AMBIENT_LUX_UPDATED "$stamp" || return 1
      HA_AMBIENT_LUX_UPDATED=$stamp
      return 2
    fi
  fi
  set_cfg HA_AMBIENT_LUX "$incoming" && set_cfg HA_AMBIENT_LUX_UPDATED "$stamp" || return 1
  HA_AMBIENT_LUX=$incoming; HA_AMBIENT_LUX_UPDATED=$stamp
  return 0
}
apply_now(){ [ -x "$ROOT_DIR/apply-queue.sh" ] && "$ROOT_DIR/apply-queue.sh" || json_error '503 Service Unavailable' 'could not queue the screen brightness update'; }
ensure_profile_watcher(){
  watcher_pid=$(cat "$ROOT_DIR/picture-watch.pid" 2>/dev/null || true)
  case "$watcher_pid" in ''|*[!0-9]*) watcher_pid='';; esac
  if [ -n "$watcher_pid" ] && [ -r "/proc/$watcher_pid/cmdline" ] && tr '\000' ' ' < "/proc/$watcher_pid/cmdline" 2>/dev/null | grep -q 'picture-watch.sh'; then return 0; fi
  nohup "$ROOT_DIR/picture-watch.sh" >/tmp/panelcomfort-picture-watch.log 2>&1 &
  echo $! > "$ROOT_DIR/picture-watch.pid"
}
stop_profile_watcher(){
  watcher_pid=$(cat "$ROOT_DIR/picture-watch.pid" 2>/dev/null || true)
  case "$watcher_pid" in ''|*[!0-9]*) watcher_pid='';; esac
  if [ -n "$watcher_pid" ] && [ -r "/proc/$watcher_pid/cmdline" ] && tr '\000' ' ' < "/proc/$watcher_pid/cmdline" 2>/dev/null | grep -q 'picture-watch.sh'; then kill "$watcher_pid" 2>/dev/null || true; fi
  rm -f "$ROOT_DIR/picture-watch.pid"
}

if [ "${REQUEST_METHOD:-GET}" = POST ]; then
  action=$(param action)
  case "$action" in
    movie_on) : > "$ROOT_DIR/override.flag"; apply_now ;;
    movie_off) rm -f "$ROOT_DIR/override.flag"; apply_now ;;
    movie_toggle) if [ -f "$ROOT_DIR/override.flag" ]; then rm -f "$ROOT_DIR/override.flag"; else : > "$ROOT_DIR/override.flag"; fi; apply_now ;;
    ambient_lux)
      lux=$(param lux); valid_int "$lux" || json_error '400 Bad Request' 'lux must be an integer from 0 to 200000'
      [ "$lux" -ge 0 ] 2>/dev/null && [ "$lux" -le 200000 ] 2>/dev/null || json_error '400 Bad Request' 'lux must be in the range 0 to 200000'
      store_lux_sample "$lux"; lux_rc=$?
      case "$lux_rc" in 0) apply_now;; 2) :;; *) json_error '500 Internal Server Error' 'could not save lux value';; esac ;;
    brightness_offset)
      offset=$(param value); valid_int "$offset" || json_error '400 Bad Request' 'offset must be an integer from -30 to 30'
      [ "$offset" -ge -30 ] 2>/dev/null && [ "$offset" -le 30 ] 2>/dev/null || json_error '400 Bad Request' 'offset must be from -30 to 30'
      set_cfg HA_BRIGHTNESS_OFFSET "$offset" || json_error '500 Internal Server Error' 'could not save offset'; apply_now ;;
    save)
      enabled=$(param enabled); dim_mode=$(param dim_mode); dim_start=$(param dim_start); dim_duration=$(param dim_duration); up_mode=$(param up_mode); undim_start=$(param undim_start); undim_duration=$(param undim_duration); curve=$(param curve); method=$(param method); min_bri=$(param min_brightness); max_bri=$(param max_brightness); movie_brightness_enabled=$(param movie_brightness_enabled); movie_brightness=$(param movie_brightness); eye_enabled=$(param eye_enabled); eye_mode=$(param eye_mode); eye_lux_threshold=$(param eye_lux_threshold); eye_timing=$(param eye_timing); eye_start=$(param eye_start); eye_end=$(param eye_end); eye_start_offset=$(param eye_start_offset); eye_end_offset=$(param eye_end_offset); lat=$(param latitude); lon=$(param longitude); sunset_offset=$(param sunset_offset); sunrise_offset=$(param sunrise_offset); lux_min=$(param ambient_lux_min); lux_max=$(param ambient_lux_max); lux_stability=$(param lux_stability); ambient_offset=$(param ambient_brightness_offset); hdr_enabled=$(param hyperhdr_enabled); hdr_min=$(param hyperhdr_min_brightness); hdr_max=$(param hyperhdr_max_brightness); profile_protection=$(param profile_protection)
      [ -n "$movie_brightness_enabled" ] || movie_brightness_enabled=${MOVIE_BRIGHTNESS_ENABLED:-0}
      [ -n "$movie_brightness" ] || movie_brightness=${MOVIE_BRIGHTNESS:-${MAX_BRIGHTNESS:-80}}
      [ -n "$eye_lux_threshold" ] || eye_lux_threshold=${EYE_LUX_THRESHOLD:-50}
      [ -n "$lux_stability" ] || lux_stability=${LUX_STABILITY:-10}
      case "$enabled" in 0|1) :;; *) json_error '400 Bad Request' 'invalid service switch';; esac
      case "$up_mode" in fixed|sunrise) :;; *) json_error '400 Bad Request' 'invalid morning trigger';; esac
      case "$dim_mode" in fixed|sunset) :;; *) json_error '400 Bad Request' 'invalid evening trigger';; esac
      case "$eye_enabled" in 0|1) :;; *) json_error '400 Bad Request' 'invalid Eye Comfort switch';; esac
      case "$movie_brightness_enabled" in 0|1) :;; *) json_error '400 Bad Request' 'invalid Movie Mode brightness switch';; esac
      case "$hdr_enabled" in 0|1) :;; *) json_error '400 Bad Request' 'invalid HyperHDR switch';; esac
      case "$profile_protection" in 0|1) :;; *) json_error '400 Bad Request' 'invalid picture profile protection switch';; esac
      case "$eye_mode" in dynamic|auto|time|on|off) :;; *) json_error '400 Bad Request' 'Eye Comfort mode must be Dynamic, Time, On or Off';; esac
      [ "$eye_mode" != auto ] || eye_mode=dynamic
      case "$eye_timing" in linked|custom) :;; *) json_error '400 Bad Request' 'Eye Comfort timing must be linked or custom';; esac
      valid_time "$dim_start" && valid_time "$undim_start" && valid_time "$eye_start" && valid_time "$eye_end" || json_error '400 Bad Request' 'times must use HH:MM'
      for n in "$dim_duration" "$undim_duration" "$min_bri" "$max_bri" "$movie_brightness" "$ambient_offset" "$eye_start_offset" "$eye_end_offset" "$hdr_min" "$hdr_max" "$sunset_offset" "$sunrise_offset"; do valid_int "$n" || json_error '400 Bad Request' 'duration or brightness field is not an integer'; done
      valid_lux_bound "$lux_min" && valid_lux_bound "$lux_max" || json_error '400 Bad Request' 'ambient lux limits must be whole values from 0 to 200000'
      valid_lux_bound "$eye_lux_threshold" || json_error '400 Bad Request' 'Eye Comfort lux threshold must be a whole value from 0 to 200000'
      valid_lux_stability "$lux_stability" || json_error '400 Bad Request' 'Lux Stability must be a whole value from 0 to 1000'
      [ "$dim_duration" -ge 0 ] && [ "$dim_duration" -le 720 ] && [ "$undim_duration" -ge 0 ] && [ "$undim_duration" -le 720 ] || json_error '400 Bad Request' 'durations must be 0 to 720 minutes'
      [ "$min_bri" -ge 0 ] && [ "$min_bri" -le 70 ] && [ "$max_bri" -ge 1 ] && [ "$max_bri" -le 100 ] && [ "$min_bri" -le "$max_bri" ] || json_error '400 Bad Request' 'brightness range must be night 0–70 and day 1–100, with night <= day'
      [ "$movie_brightness" -ge 0 ] && [ "$movie_brightness" -le 100 ] || json_error '400 Bad Request' 'Movie Mode brightness must be from 0 to 100'
      [ "$lux_min" -ge 0 ] && [ "$lux_min" -le 199999 ] && [ "$lux_max" -ge 1 ] && [ "$lux_max" -le 200000 ] && [ "$lux_min" -lt "$lux_max" ] || json_error '400 Bad Request' 'ambient lux limits must be 0–200000, with minimum below maximum'
      [ "$ambient_offset" -ge -30 ] && [ "$ambient_offset" -le 30 ] || json_error '400 Bad Request' 'ambient brightness offset must be -30 to 30'
      [ "$eye_start_offset" -ge -720 ] && [ "$eye_start_offset" -le 720 ] && [ "$eye_end_offset" -ge -720 ] && [ "$eye_end_offset" -le 720 ] || json_error '400 Bad Request' 'Eye Comfort offsets must be -720 to 720 minutes'
      [ "$hdr_min" -ge 0 ] && [ "$hdr_min" -le 100 ] && [ "$hdr_max" -ge 1 ] && [ "$hdr_max" -le 100 ] && [ "$hdr_min" -le "$hdr_max" ] || json_error '400 Bad Request' 'HyperHDR limits must be 0–100%, with night minimum no higher than day maximum'
      case "$method" in duration|solar|ambient|tv-sensor) :;; *) json_error '400 Bad Request' 'invalid fade calculation';; esac
      case "$curve" in linear|easein|easeout|smooth|smootherstep|twilight|rolloff-soft|rolloff|rolloff-strong|exponential|gamma-late|gamma-early) :;; *) json_error '400 Bad Request' 'invalid fade curve';; esac
      valid_int "$sunset_offset" && valid_int "$sunrise_offset" || json_error '400 Bad Request' 'solar offsets must be integers'
      [ "$sunset_offset" -ge -180 ] && [ "$sunset_offset" -le 180 ] && [ "$sunrise_offset" -ge -180 ] && [ "$sunrise_offset" -le 180 ] || json_error '400 Bad Request' 'solar offsets must be between -180 and 180 minutes'
      if [ -n "$lat" ] || [ -n "$lon" ]; then
        printf '%s' "$lat" | grep -Eq '^-?[0-9]{1,2}(\.[0-9]{1,6})?$' || json_error '400 Bad Request' 'latitude is invalid'
        printf '%s' "$lon" | grep -Eq '^-?[0-9]{1,3}(\.[0-9]{1,6})?$' || json_error '400 Bad Request' 'longitude is invalid'
        awk -v a="$lat" -v b="$lon" 'BEGIN {exit !(a>=-89 && a<=89 && b>=-180 && b<=180)}' || json_error '400 Bad Request' 'coordinates are out of range'
      fi
      if [ "$dim_mode" = sunset ] || [ "$up_mode" = sunrise ] || [ "$method" = solar ]; then [ -n "$lat" ] && [ -n "$lon" ] || json_error '400 Bad Request' 'sunrise, sunset and solar-elevation modes need latitude and longitude'; fi
      for pair in "ENABLED=$enabled" "DIM_MODE=$dim_mode" "DIM_START=$dim_start" "DIM_DURATION=$dim_duration" "UP_MODE=$up_mode" "UNDIM_START=$undim_start" "UNDIM_DURATION=$undim_duration" "FADE_CURVE=$curve" "FADE_METHOD=$method" "MIN_BRIGHTNESS=$min_bri" "MAX_BRIGHTNESS=$max_bri" "MOVIE_BRIGHTNESS_ENABLED=$movie_brightness_enabled" "MOVIE_BRIGHTNESS=$movie_brightness" "EYE_ENABLED=$eye_enabled" "HA_EYE_COMFORT_OVERRIDE=$eye_mode" "EYE_LUX_THRESHOLD=$eye_lux_threshold" "EYE_TIMING=$eye_timing" "EYE_START=$eye_start" "EYE_END=$eye_end" "EYE_START_OFFSET=$eye_start_offset" "EYE_END_OFFSET=$eye_end_offset" "AMBIENT_LUX_MIN=$lux_min" "AMBIENT_LUX_MAX=$lux_max" "LUX_STABILITY=$lux_stability" "AMBIENT_BRIGHTNESS_OFFSET=$ambient_offset" "HYPERHDR_ENABLED=$hdr_enabled" "HYPERHDR_MIN_BRIGHTNESS=$hdr_min" "HYPERHDR_MAX_BRIGHTNESS=$hdr_max" "PROFILE_PROTECTION_ENABLED=$profile_protection" "SUNSET_LAT=$lat" "SUNSET_LON=$lon" "SUNSET_OFFSET=$sunset_offset" "SUNRISE_OFFSET=$sunrise_offset"; do set_cfg "${pair%%=*}" "${pair#*=}" || json_error '500 Internal Server Error' 'could not write configuration'; done
      if [ "$profile_protection" = 1 ] && [ -x "$ROOT_DIR/picture-watch.sh" ]; then ensure_profile_watcher; else stop_profile_watcher; fi
      chmod 600 "$CFG"; apply_now
      ;;
    *) json_error '400 Bad Request' 'unknown action';;
  esac
fi

# Actions above may have changed config.env; reload before composing the response
# so the dashboard immediately sees the new lux reading, offset, and settings.
. "$CFG"
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n'
[ -r "$ROOT_DIR/tv-sensor-status" ] && . "$ROOT_DIR/tv-sensor-status"
values=$($ROOT_DIR/daemon.sh --calculate 2>/dev/null || echo '0 off unavailable 0')
set -- $values; backlight=${1:-0}; eye=${2:-off}; phase=${3:-unavailable}; hdr=${4:-0}
case "$backlight" in ''|*[!0-9]*) backlight=0;; esac
case "$hdr" in ''|*[!0-9]*) hdr=0;; esac
case "$eye" in on|off) ;; *) eye=off;; esac
case "$phase" in *[!a-zA-Z0-9_-]*|'') phase=unavailable;; esac
case "${HA_AMBIENT_LUX:-0}" in ''|*[!0-9]*) lux=0;; *) lux=${HA_AMBIENT_LUX:-0};; esac
case "${HA_AMBIENT_LUX_UPDATED:-0}" in ''|*[!0-9]*) lux_updated=0;; *) lux_updated=${HA_AMBIENT_LUX_UPDATED:-0};; esac
case "${HA_BRIGHTNESS_OFFSET:-0}" in ''|*[!0-9-]*) offset=0;; *) offset=${HA_BRIGHTNESS_OFFSET:-0};; esac
case "${SUNSET_LAT:-}" in ''|*[!0-9.-]*) lat_json='';; *) lat_json=${SUNSET_LAT};; esac
case "${SUNSET_LON:-}" in ''|*[!0-9.-]*) lon_json='';; *) lon_json=${SUNSET_LON};; esac
case "${TV_SENSOR_AVAILABLE:-0}" in 1) tv_available=true;; *) tv_available=false;; esac
case "${TV_SENSOR_LUMINANCE:-0}" in ''|*[!0-9]*) tv_luminance=0;; *) tv_luminance=${TV_SENSOR_LUMINANCE:-0};; esac
[ -f "$ROOT_DIR/override.flag" ] && movie=true || movie=false
[ "${ENABLED:-1}" = 1 ] && enabled=true || enabled=false
[ "${EYE_ENABLED:-1}" = 1 ] && eye_enabled=true || eye_enabled=false
[ "${HYPERHDR_ENABLED:-0}" = 1 ] && hdr_enabled=true || hdr_enabled=false
[ "${PROFILE_PROTECTION_ENABLED:-1}" = 1 ] && profile_protection=true || profile_protection=false
eye_timing=${EYE_TIMING:-linked}; case "$eye_timing" in linked|custom) ;; *) eye_timing=linked;; esac
eye_mode=${HA_EYE_COMFORT_OVERRIDE:-dynamic}; case "$eye_mode" in auto) eye_mode=dynamic;; dynamic|time|on|off) ;; *) eye_mode=dynamic;; esac
eye_lux_threshold=${EYE_LUX_THRESHOLD:-50}; case "$eye_lux_threshold" in ''|*[!0-9]*) eye_lux_threshold=50;; esac; [ "$eye_lux_threshold" -le 200000 ] 2>/dev/null || eye_lux_threshold=50
ambient_lux_min=${AMBIENT_LUX_MIN:-5}; case "$ambient_lux_min" in ''|*[!0-9]*) ambient_lux_min=5;; esac
ambient_lux_max=${AMBIENT_LUX_MAX:-500}; case "$ambient_lux_max" in ''|*[!0-9]*) ambient_lux_max=500;; esac
lux_stability=${LUX_STABILITY:-10}; valid_lux_stability "$lux_stability" || lux_stability=10
ambient_brightness_offset=${AMBIENT_BRIGHTNESS_OFFSET:-0}; case "$ambient_brightness_offset" in ''|*[!0-9-]*) ambient_brightness_offset=0;; esac
eye_start_offset=${EYE_START_OFFSET:-15}; case "$eye_start_offset" in ''|*[!0-9-]*) eye_start_offset=15;; esac
eye_end_offset=${EYE_END_OFFSET:-0}; case "$eye_end_offset" in ''|*[!0-9-]*) eye_end_offset=0;; esac
hyperhdr_min=${HYPERHDR_MIN_BRIGHTNESS:-12}; case "$hyperhdr_min" in ''|*[!0-9]*) hyperhdr_min=12;; esac
hyperhdr_max=${HYPERHDR_MAX_BRIGHTNESS:-60}; case "$hyperhdr_max" in ''|*[!0-9]*) hyperhdr_max=60;; esac
apply_status=$(sed -n 's/^SCREEN_APPLY_STATUS=//p' "$ROOT_DIR/apply-status" 2>/dev/null | tail -n 1); case "$apply_status" in sent|rejected|error|no-luna-send) ;; *) apply_status=unknown;; esac
if [ -f "$ROOT_DIR/apply-queue.pending" ] || [ -d "$ROOT_DIR/apply-queue.lock" ] || [ -d "$ROOT_DIR/apply.lock" ]; then apply_status=queued; fi
apply_backlight=$(sed -n 's/^SCREEN_APPLY_BACKLIGHT=//p' "$ROOT_DIR/apply-status" 2>/dev/null | tail -n 1); case "$apply_backlight" in ''|*[!0-9]*) apply_backlight=0;; esac
apply_updated=$(sed -n 's/^SCREEN_APPLY_UPDATED=//p' "$ROOT_DIR/apply-status" 2>/dev/null | tail -n 1); case "$apply_updated" in ''|*[!0-9]*) apply_updated=0;; esac
printf '{"ok":true,"device_id":"%s","time":"%s","date":"%s","movie_override":%s,"movie_brightness_enabled":%s,"movie_brightness":%s,"service_enabled":%s,"backlight":%s,"eye_comfort":"%s","eye_enabled":%s,"eye_mode":"%s","eye_lux_threshold":%s,"profile_protection_enabled":%s,"hyperhdr_enabled":%s,"hyperhdr_min_brightness":%s,"hyperhdr_max_brightness":%s,"phase":"%s","hyperhdr_brightness":%s,"brightness_offset":%s,"ambient_lux":%s,"ambient_lux_updated":%s,"ambient_lux_min":%s,"ambient_lux_max":%s,"lux_stability":%s,"ambient_brightness_offset":%s,"tv_sensor_available":%s,"tv_sensor_luminance":%s,"screen_apply_status":"%s","screen_apply_backlight":%s,"screen_apply_updated":%s,"dim_mode":"%s","dim_start":"%s","dim_duration":%s,"up_mode":"%s","undim_start":"%s","undim_duration":%s,"fade_method":"%s","fade_curve":"%s","min_brightness":%s,"max_brightness":%s,"eye_start":"%s","eye_end":"%s","eye_timing":"%s","eye_start_offset":%s,"eye_end_offset":%s,"latitude":"%s","longitude":"%s","sunset_offset":%s,"sunrise_offset":%s}\n' \
  "${HA_DEVICE_ID:-unknown}" "$(date +%H:%M:%S)" "$(date +%Y-%m-%d)" "$movie" "$([ "${MOVIE_BRIGHTNESS_ENABLED:-0}" = 1 ] && echo true || echo false)" "${MOVIE_BRIGHTNESS:-80}" "$enabled" "$backlight" "$eye" "$eye_enabled" "$eye_mode" "$eye_lux_threshold" "$profile_protection" "$hdr_enabled" "$hyperhdr_min" "$hyperhdr_max" "$phase" "$hdr" "$offset" "$lux" "$lux_updated" "$ambient_lux_min" "$ambient_lux_max" "$lux_stability" "$ambient_brightness_offset" "$tv_available" "$tv_luminance" "$apply_status" "$apply_backlight" "$apply_updated" \
  "${DIM_MODE:-fixed}" "${DIM_START:-21:00}" "${DIM_DURATION:-60}" "${UP_MODE:-fixed}" "${UNDIM_START:-06:30}" "${UNDIM_DURATION:-45}" "${FADE_METHOD:-duration}" "${FADE_CURVE:-smooth}" "${MIN_BRIGHTNESS:-18}" "${MAX_BRIGHTNESS:-80}" "${EYE_START:-21:30}" "${EYE_END:-06:30}" "$eye_timing" "$eye_start_offset" "$eye_end_offset" "$lat_json" "$lon_json" "${SUNSET_OFFSET:--20}" "${SUNRISE_OFFSET:-0}"
