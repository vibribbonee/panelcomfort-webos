#!/bin/sh
# Tokenless Home Assistant API, restricted to private IPv4 clients.
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
respond_error(){ code=$1; msg=$2; printf 'Status: %s\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n' "$code"; printf '{"ok":false,"error":"%s"}\n' "$msg"; exit 0; }
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
[ "${HA_API_ENABLED:-0}" = 1 ] || respond_error '404 Not Found' 'Home Assistant API is disabled'
local_client || respond_error '403 Forbidden' 'private IPv4 client required'
[ -n "${HA_DEVICE_ID:-}" ] || respond_error '503 Service Unavailable' 'device ID unavailable'
movie_override(){ [ -f "$ROOT_DIR/override.flag" ]; }
CONFIG_LOCK="$ROOT_DIR/config-write.lock"
case "${QUERY_STRING:-}" in action=status|status=1) ;; *) acquire_config_lock;; esac
write_cfg(){
  key=$1; value=$2
  case "$key" in ENABLED|EYE_ENABLED|HA_EYE_COMFORT_OVERRIDE|EYE_LUX_THRESHOLD|HYPERHDR_ENABLED|PROFILE_PROTECTION_ENABLED|MIN_BRIGHTNESS|MAX_BRIGHTNESS|MOVIE_BRIGHTNESS_ENABLED|MOVIE_BRIGHTNESS|HYPERHDR_MIN_BRIGHTNESS|HYPERHDR_MAX_BRIGHTNESS|HA_BRIGHTNESS_OFFSET|HA_AMBIENT_LUX|HA_AMBIENT_LUX_UPDATED|AMBIENT_LUX_MIN|AMBIENT_LUX_MAX|LUX_STABILITY|AMBIENT_BRIGHTNESS_OFFSET|FADE_METHOD|FADE_CURVE|DIM_MODE|DIM_START|DIM_DURATION|UP_MODE|UNDIM_START|UNDIM_DURATION|EYE_TIMING|EYE_START|EYE_END|EYE_START_OFFSET|EYE_END_OFFSET|SUNSET_OFFSET|SUNRISE_OFFSET|SUNSET_LAT|SUNSET_LON) :;; *) return 1;; esac
  if grep -q "^${key}=" "$CFG"; then
    sed "s/^${key}=.*/${key}=${value}/" "$CFG" > "$CFG.tmp.$$" && chmod 600 "$CFG.tmp.$$" && mv "$CFG.tmp.$$" "$CFG" || return 1
  else printf '%s=%s\n' "$key" "$value" >> "$CFG" || return 1; fi
  chmod 600 "$CFG"
}
apply_now(){
  [ -x "$ROOT_DIR/apply-queue.sh" ] && "$ROOT_DIR/apply-queue.sh" || return 1
}
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
valid_brightness(){ case "$1" in ''|*[!0-9]*) return 1;; esac; [ "$(printf '%s' "$1" | wc -c | tr -d ' ')" -le 3 ] && [ "$1" -le 100 ] 2>/dev/null; }
valid_lux_bound(){ case "$1" in ''|*[!0-9]*) return 1;; esac; [ "$(printf '%s' "$1" | wc -c | tr -d ' ')" -le 6 ] && [ "$1" -le 200000 ] 2>/dev/null; }
valid_lux_stability(){ case "$1" in ''|*[!0-9]*) return 1;; esac; [ "$(printf '%s' "$1" | wc -c | tr -d ' ')" -le 4 ] && [ "$1" -le 1000 ] 2>/dev/null; }
valid_int_range(){ case "$1" in ''|*[!0-9-]*|-) return 1;; esac; [ "$(printf '%s' "$1" | wc -c | tr -d ' ')" -le 4 ] && [ "$1" -ge "$2" ] 2>/dev/null && [ "$1" -le "$3" ] 2>/dev/null; }
valid_decimal_range(){ case "$1" in ''|*[!0-9.-]*) return 1;; esac; [ "$(printf '%s' "$1" | wc -c | tr -d ' ')" -le 10 ] || return 1; awk -v value="$1" -v low="$2" -v high="$3" 'BEGIN { if (value !~ /^-?[0-9]+([.][0-9]+)?$/ || value < low || value > high) exit 1; }'; }
valid_time(){ case "$1" in [01][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]) return 0;; *) return 1;; esac; }
store_lux_sample(){
  incoming=$1; stamp=$(date +%s); stability=${LUX_STABILITY:-10}
  valid_lux_stability "$stability" || stability=10
  previous=${HA_AMBIENT_LUX:-}; previous_stamp=${HA_AMBIENT_LUX_UPDATED:-0}
  case "$previous" in ''|*[!0-9]*) previous='';; esac
  case "$previous_stamp" in ''|*[!0-9]*) previous_stamp=0;; esac
  if [ -n "$previous" ] && [ "$previous" -le 200000 ] 2>/dev/null && [ "$previous_stamp" -gt 0 ] 2>/dev/null && [ "$stamp" -ge "$previous_stamp" ] 2>/dev/null && [ $((stamp-previous_stamp)) -le 180 ] 2>/dev/null; then
    difference=$((incoming - previous)); [ "$difference" -lt 0 ] && difference=$((-difference))
    if [ "$difference" -le "$stability" ] 2>/dev/null; then
      write_cfg HA_AMBIENT_LUX_UPDATED "$stamp" || return 1
      HA_AMBIENT_LUX_UPDATED=$stamp
      return 2
    fi
  fi
  write_cfg HA_AMBIENT_LUX "$incoming" && write_cfg HA_AMBIENT_LUX_UPDATED "$stamp" || return 1
  HA_AMBIENT_LUX=$incoming; HA_AMBIENT_LUX_UPDATED=$stamp
  return 0
}
case "${QUERY_STRING:-}" in
  service=on|service=off)
    requested=${QUERY_STRING#service=}; write_cfg ENABLED "$([ "$requested" = on ] && echo 1 || echo 0)" || respond_error '500 Internal Server Error' 'could not save scheduler setting'
    ENABLED=$([ "$requested" = on ] && echo 1 || echo 0); apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen setting; see service.log' ;;
  movie=on) : > "$ROOT_DIR/override.flag"; apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen brightness update; see service.log' ;;
  movie=off) rm -f "$ROOT_DIR/override.flag"; apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen brightness update; see service.log' ;;
  movie=toggle) if movie_override; then rm -f "$ROOT_DIR/override.flag"; else : > "$ROOT_DIR/override.flag"; fi; apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen brightness update; see service.log' ;;
  movie_brightness_custom=on|movie_brightness_custom=off)
    requested=${QUERY_STRING#movie_brightness_custom=}; write_cfg MOVIE_BRIGHTNESS_ENABLED "$([ "$requested" = on ] && echo 1 || echo 0)" || respond_error '500 Internal Server Error' 'could not save Movie Mode brightness setting'
    MOVIE_BRIGHTNESS_ENABLED=$([ "$requested" = on ] && echo 1 || echo 0); apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen brightness update; see service.log' ;;
  movie_brightness=*)
    requested=${QUERY_STRING#movie_brightness=}; valid_brightness "$requested" || respond_error '400 Bad Request' 'Movie Mode brightness must be an integer from 0 to 100'
    write_cfg MOVIE_BRIGHTNESS "$requested" && write_cfg MOVIE_BRIGHTNESS_ENABLED 1 || respond_error '500 Internal Server Error' 'could not save Movie Mode brightness'
    MOVIE_BRIGHTNESS=$requested; MOVIE_BRIGHTNESS_ENABLED=1; apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen brightness update; see service.log' ;;
  eye_schedule=on|eye_schedule=off)
    requested=${QUERY_STRING#eye_schedule=}; write_cfg EYE_ENABLED "$([ "$requested" = on ] && echo 1 || echo 0)" || respond_error '500 Internal Server Error' 'could not save Eye Comfort setting'
    EYE_ENABLED=$([ "$requested" = on ] && echo 1 || echo 0); apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen setting; see service.log' ;;
  eye_comfort_mode=dynamic|eye_comfort_mode=auto|eye_comfort_mode=time|eye_comfort_mode=on|eye_comfort_mode=off)
    requested=${QUERY_STRING#eye_comfort_mode=}
    [ "$requested" != auto ] || requested=dynamic
    write_cfg HA_EYE_COMFORT_OVERRIDE "$requested" || respond_error '500 Internal Server Error' 'could not save Eye Comfort mode'
    HA_EYE_COMFORT_OVERRIDE=$requested; apply_now || respond_error '502 Bad Gateway' 'TV did not accept the Eye Comfort setting; see service.log' ;;
  eye_lux_threshold=*)
    requested=${QUERY_STRING#eye_lux_threshold=}; valid_lux_bound "$requested" || respond_error '400 Bad Request' 'Eye Comfort lux threshold must be an integer from 0 to 200000'
    write_cfg EYE_LUX_THRESHOLD "$requested" || respond_error '500 Internal Server Error' 'could not save Eye Comfort lux threshold'
    EYE_LUX_THRESHOLD=$requested; apply_now || respond_error '502 Bad Gateway' 'TV did not accept the Eye Comfort setting; see service.log' ;;
  hyperhdr=on|hyperhdr=off)
    requested=${QUERY_STRING#hyperhdr=}; write_cfg HYPERHDR_ENABLED "$([ "$requested" = on ] && echo 1 || echo 0)" || respond_error '500 Internal Server Error' 'could not save HyperHDR setting'
    HYPERHDR_ENABLED=$([ "$requested" = on ] && echo 1 || echo 0); apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen setting; see service.log' ;;
  profile_protection=on|profile_protection=off)
    requested=${QUERY_STRING#profile_protection=}; write_cfg PROFILE_PROTECTION_ENABLED "$([ "$requested" = on ] && echo 1 || echo 0)" || respond_error '500 Internal Server Error' 'could not save picture profile protection setting'
    PROFILE_PROTECTION_ENABLED=$([ "$requested" = on ] && echo 1 || echo 0)
    if [ "$PROFILE_PROTECTION_ENABLED" = 1 ] && [ -x "$ROOT_DIR/picture-watch.sh" ]; then ensure_profile_watcher; else stop_profile_watcher; fi ;;
  ambient_lux=*)
    lux=${QUERY_STRING#ambient_lux=}
    case "$lux" in ''|*[!0-9]*) respond_error '400 Bad Request' 'ambient lux must be an integer from 0 to 200000' ;; esac
    [ "$(printf '%s' "$lux" | wc -c | tr -d ' ')" -le 6 ] || respond_error '400 Bad Request' 'ambient lux is out of range'
    [ "$lux" -le 200000 ] 2>/dev/null || respond_error '400 Bad Request' 'ambient lux is out of range'
    store_lux_sample "$lux"; lux_rc=$?
    case "$lux_rc" in
      0) if ! movie_override; then apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen setting; see service.log'; fi ;;
      2) : ;;
      *) respond_error '500 Internal Server Error' 'could not save lux value' ;;
    esac ;;
  brightness_offset=*)
    requested=${QUERY_STRING#brightness_offset=}
    case "$requested" in ''|*[!0-9-]*) respond_error '400 Bad Request' 'brightness offset must be an integer from -30 to 30' ;; esac
    [ "$(printf '%s' "$requested" | wc -c | tr -d ' ')" -le 3 ] || respond_error '400 Bad Request' 'brightness offset is out of range'
    [ "$requested" -ge -30 ] 2>/dev/null && [ "$requested" -le 30 ] 2>/dev/null || respond_error '400 Bad Request' 'brightness offset must be -30 to 30'
    write_cfg HA_BRIGHTNESS_OFFSET "$requested" || respond_error '500 Internal Server Error' 'could not save brightness offset'
    HA_BRIGHTNESS_OFFSET=$requested; apply_now || respond_error '502 Bad Gateway' 'TV did not accept the screen brightness update; see service.log' ;;
  min_brightness=*|max_brightness=*|hyperhdr_min_brightness=*|hyperhdr_max_brightness=*)
    key=${QUERY_STRING%%=*}; requested=${QUERY_STRING#*=}; valid_brightness "$requested" || respond_error '400 Bad Request' 'brightness must be an integer from 0 to 100'
    case "$key" in
      min_brightness) [ "$requested" -le "${MAX_BRIGHTNESS:-80}" ] || respond_error '400 Bad Request' 'night minimum cannot exceed day maximum'; cfg_key=MIN_BRIGHTNESS; MIN_BRIGHTNESS=$requested ;;
      max_brightness) [ "$requested" -ge "${MIN_BRIGHTNESS:-18}" ] || respond_error '400 Bad Request' 'day maximum cannot be below night minimum'; cfg_key=MAX_BRIGHTNESS; MAX_BRIGHTNESS=$requested ;;
      hyperhdr_min_brightness) [ "$requested" -le "${HYPERHDR_MAX_BRIGHTNESS:-60}" ] || respond_error '400 Bad Request' 'HyperHDR night minimum cannot exceed day maximum'; cfg_key=HYPERHDR_MIN_BRIGHTNESS; HYPERHDR_MIN_BRIGHTNESS=$requested ;;
      hyperhdr_max_brightness) [ "$requested" -ge "${HYPERHDR_MIN_BRIGHTNESS:-12}" ] || respond_error '400 Bad Request' 'HyperHDR day maximum cannot be below night minimum'; cfg_key=HYPERHDR_MAX_BRIGHTNESS; HYPERHDR_MAX_BRIGHTNESS=$requested ;;
    esac
    write_cfg "$cfg_key" "$requested" || respond_error '500 Internal Server Error' 'could not save brightness setting'
    apply_now || respond_error '502 Bad Gateway' 'TV did not accept the brightness update; see service.log' ;;
  lux_stability=*|ambient_lux_min=*|ambient_lux_max=*|ambient_brightness_offset=*|fade_method=*|fade_curve=*|dim_mode=*|dim_start=*|dim_duration=*|up_mode=*|undim_start=*|undim_duration=*|eye_timing=*|eye_start=*|eye_end=*|eye_start_offset=*|eye_end_offset=*|sunset_offset=*|sunrise_offset=*|sunset_lat=*|sunset_lon=*)
    key=${QUERY_STRING%%=*}; requested=${QUERY_STRING#*=}
    case "$key" in
      lux_stability) valid_lux_stability "$requested" || respond_error '400 Bad Request' 'Lux Stability must be a whole value from 0 to 1000'; cfg_key=LUX_STABILITY ;;
      ambient_lux_min) valid_lux_bound "$requested" || respond_error '400 Bad Request' 'minimum ambient lux must be from 0 to 200000'; [ "$requested" -lt "${AMBIENT_LUX_MAX:-500}" ] 2>/dev/null || respond_error '400 Bad Request' 'minimum ambient lux must be below maximum ambient lux'; cfg_key=AMBIENT_LUX_MIN ;;
      ambient_lux_max) valid_lux_bound "$requested" && [ "$requested" -ge 1 ] 2>/dev/null || respond_error '400 Bad Request' 'maximum ambient lux must be from 1 to 200000'; [ "$requested" -gt "${AMBIENT_LUX_MIN:-5}" ] 2>/dev/null || respond_error '400 Bad Request' 'maximum ambient lux must be above minimum ambient lux'; cfg_key=AMBIENT_LUX_MAX ;;
      ambient_brightness_offset) valid_int_range "$requested" -30 30 || respond_error '400 Bad Request' 'ambient brightness offset must be -30 to 30'; cfg_key=AMBIENT_BRIGHTNESS_OFFSET ;;
      fade_method) case "$requested" in duration|solar|ambient|tv-sensor) cfg_key=FADE_METHOD;; *) respond_error '400 Bad Request' 'invalid brightness calculation method';; esac ;;
      fade_curve) case "$requested" in linear|easein|easeout|smooth|smootherstep|twilight|rolloff-soft|rolloff|rolloff-strong|exponential|gamma-late|gamma-early) cfg_key=FADE_CURVE;; *) respond_error '400 Bad Request' 'invalid fade curve';; esac ;;
      dim_mode) case "$requested" in fixed|sunset) cfg_key=DIM_MODE;; *) respond_error '400 Bad Request' 'invalid evening trigger';; esac ;;
      up_mode) case "$requested" in fixed|sunrise) cfg_key=UP_MODE;; *) respond_error '400 Bad Request' 'invalid morning trigger';; esac ;;
      eye_timing) case "$requested" in linked|custom) cfg_key=EYE_TIMING;; *) respond_error '400 Bad Request' 'invalid Eye Comfort timing';; esac ;;
      dim_start) valid_time "$requested" || respond_error '400 Bad Request' 'evening time must use HH:MM'; cfg_key=DIM_START ;;
      undim_start) valid_time "$requested" || respond_error '400 Bad Request' 'morning time must use HH:MM'; cfg_key=UNDIM_START ;;
      eye_start) valid_time "$requested" || respond_error '400 Bad Request' 'Eye Comfort start must use HH:MM'; cfg_key=EYE_START ;;
      eye_end) valid_time "$requested" || respond_error '400 Bad Request' 'Eye Comfort end must use HH:MM'; cfg_key=EYE_END ;;
      dim_duration) valid_int_range "$requested" 0 720 || respond_error '400 Bad Request' 'evening duration must be 0 to 720 minutes'; cfg_key=DIM_DURATION ;;
      undim_duration) valid_int_range "$requested" 0 720 || respond_error '400 Bad Request' 'morning duration must be 0 to 720 minutes'; cfg_key=UNDIM_DURATION ;;
      eye_start_offset) valid_int_range "$requested" -720 720 || respond_error '400 Bad Request' 'Eye Comfort start offset must be -720 to 720 minutes'; cfg_key=EYE_START_OFFSET ;;
      eye_end_offset) valid_int_range "$requested" -720 720 || respond_error '400 Bad Request' 'Eye Comfort end offset must be -720 to 720 minutes'; cfg_key=EYE_END_OFFSET ;;
      sunset_offset) valid_int_range "$requested" -180 180 || respond_error '400 Bad Request' 'sunset offset must be -180 to 180 minutes'; cfg_key=SUNSET_OFFSET ;;
      sunrise_offset) valid_int_range "$requested" -180 180 || respond_error '400 Bad Request' 'sunrise offset must be -180 to 180 minutes'; cfg_key=SUNRISE_OFFSET ;;
      sunset_lat) valid_decimal_range "$requested" -89 89 || respond_error '400 Bad Request' 'latitude must be between -89 and 89'; cfg_key=SUNSET_LAT ;;
      sunset_lon) valid_decimal_range "$requested" -180 180 || respond_error '400 Bad Request' 'longitude must be between -180 and 180'; cfg_key=SUNSET_LON ;;
    esac
    write_cfg "$cfg_key" "$requested" || respond_error '500 Internal Server Error' 'could not save schedule setting'
    . "$CFG"; apply_now || respond_error '502 Bad Gateway' 'TV did not accept the schedule setting; see service.log' ;;
  action=status|status=1) ;;
  *) respond_error '400 Bad Request' 'Use movie=on/off/toggle, movie_brightness=VALUE, brightness settings, schedule selectors and times, eye_comfort_mode=dynamic/time/on/off, eye_lux_threshold=VALUE, ambient_lux=VALUE, or action=status' ;;
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
if [ "${PROFILE_PROTECTION_ENABLED:-1}" = 1 ]; then profile_protection_enabled=true; else profile_protection_enabled=false; fi
if [ "${MOVIE_BRIGHTNESS_ENABLED:-0}" = 1 ]; then movie_brightness_enabled=true; else movie_brightness_enabled=false; fi
apply_status=$(sed -n 's/^SCREEN_APPLY_STATUS=//p' "$ROOT_DIR/apply-status" 2>/dev/null | tail -n 1); case "$apply_status" in sent|rejected|error|no-luna-send) ;; *) apply_status=unknown;; esac
if [ -f "$ROOT_DIR/apply-queue.pending" ] || [ -d "$ROOT_DIR/apply-queue.lock" ] || [ -d "$ROOT_DIR/apply.lock" ]; then apply_status=queued; fi
apply_backlight=$(sed -n 's/^SCREEN_APPLY_BACKLIGHT=//p' "$ROOT_DIR/apply-status" 2>/dev/null | tail -n 1); case "$apply_backlight" in ''|*[!0-9]*) apply_backlight=0;; esac
apply_updated=$(sed -n 's/^SCREEN_APPLY_UPDATED=//p' "$ROOT_DIR/apply-status" 2>/dev/null | tail -n 1); case "$apply_updated" in ''|*[!0-9]*) apply_updated=0;; esac
offset=${HA_BRIGHTNESS_OFFSET:-0}; case "$offset" in ''|*[!0-9-]*) offset=0;; esac
fade_method=${FADE_METHOD:-duration}; case "$fade_method" in duration|solar|ambient|tv-sensor) ;; *) fade_method=duration;; esac
fade_curve=${FADE_CURVE:-smooth}; case "$fade_curve" in linear|easein|easeout|smooth|smootherstep|twilight|rolloff-soft|rolloff|rolloff-strong|exponential|gamma-late|gamma-early) ;; *) fade_curve=smooth;; esac
dim_mode=${DIM_MODE:-fixed}; case "$dim_mode" in fixed|sunset) ;; *) dim_mode=fixed;; esac
up_mode=${UP_MODE:-fixed}; case "$up_mode" in fixed|sunrise) ;; *) up_mode=fixed;; esac
eye_timing=${EYE_TIMING:-linked}; case "$eye_timing" in linked|custom) ;; *) eye_timing=linked;; esac
eye_mode=${HA_EYE_COMFORT_OVERRIDE:-dynamic}; case "$eye_mode" in auto) eye_mode=dynamic;; dynamic|time|on|off) ;; *) eye_mode=dynamic;; esac
eye_lux_threshold=${EYE_LUX_THRESHOLD:-50}; case "$eye_lux_threshold" in ''|*[!0-9]*) eye_lux_threshold=50;; esac; [ "$eye_lux_threshold" -le 200000 ] 2>/dev/null || eye_lux_threshold=50
latitude=${SUNSET_LAT:-}; valid_decimal_range "$latitude" -89 89 || latitude=null; [ -n "$latitude" ] || latitude=null
longitude=${SUNSET_LON:-}; valid_decimal_range "$longitude" -180 180 || longitude=null; [ -n "$longitude" ] || longitude=null
lux=${HA_AMBIENT_LUX:-null}; case "$lux" in ''|*[!0-9]*) lux=null;; esac
lux_min=${AMBIENT_LUX_MIN:-5}; valid_lux_bound "$lux_min" || lux_min=5
lux_max=${AMBIENT_LUX_MAX:-500}; valid_lux_bound "$lux_max" && [ "$lux_max" -ge 1 ] 2>/dev/null || lux_max=500
[ "$lux_min" -lt "$lux_max" ] 2>/dev/null || { lux_min=5; lux_max=500; }
lux_stability=${LUX_STABILITY:-10}; valid_lux_stability "$lux_stability" || lux_stability=10
ambient_offset=${AMBIENT_BRIGHTNESS_OFFSET:-0}; valid_int_range "$ambient_offset" -30 30 || ambient_offset=0
printf '{"ok":true,"device_id":"%s","movie_override":%s,"movie_brightness_enabled":%s,"movie_brightness":%s,"service_enabled":%s,"eye_comfort":"%s","eye_schedule_enabled":%s,"eye_comfort_mode":"%s","eye_lux_threshold":%s,"backlight":%s,"backlight_offset":%s,"min_brightness":%s,"max_brightness":%s,"hyperhdr_min_brightness":%s,"hyperhdr_max_brightness":%s,"ambient_lux":%s,"ambient_lux_min":%s,"ambient_lux_max":%s,"lux_stability":%s,"ambient_brightness_offset":%s,"fade_method":"%s","fade_curve":"%s","dim_mode":"%s","dim_start":"%s","dim_duration":%s,"up_mode":"%s","undim_start":"%s","undim_duration":%s,"eye_timing":"%s","eye_start":"%s","eye_end":"%s","eye_start_offset":%s,"eye_end_offset":%s,"sunset_offset":%s,"sunrise_offset":%s,"sunset_lat":%s,"sunset_lon":%s,"hyperhdr_enabled":%s,"profile_protection_enabled":%s,"hyperhdr_brightness":%s,"screen_apply_status":"%s","screen_apply_backlight":%s,"screen_apply_updated":%s,"phase":"%s"}\n' \
  "$HA_DEVICE_ID" "$override" "$movie_brightness_enabled" "${MOVIE_BRIGHTNESS:-80}" "$enabled" "$eye" "$eye_schedule" "$eye_mode" "$eye_lux_threshold" "$backlight" "$offset" "${MIN_BRIGHTNESS:-18}" "${MAX_BRIGHTNESS:-80}" "${HYPERHDR_MIN_BRIGHTNESS:-12}" "${HYPERHDR_MAX_BRIGHTNESS:-60}" "$lux" "$lux_min" "$lux_max" "$lux_stability" "$ambient_offset" "$fade_method" "$fade_curve" "$dim_mode" "${DIM_START:-21:00}" "${DIM_DURATION:-60}" "$up_mode" "${UNDIM_START:-06:30}" "${UNDIM_DURATION:-45}" "$eye_timing" "${EYE_START:-21:30}" "${EYE_END:-06:30}" "${EYE_START_OFFSET:-15}" "${EYE_END_OFFSET:-0}" "${SUNSET_OFFSET:--20}" "${SUNRISE_OFFSET:-0}" "$latitude" "$longitude" "$hdr_enabled" "$profile_protection_enabled" "$hdr_brightness" "$apply_status" "$apply_backlight" "$apply_updated" "$phase"
