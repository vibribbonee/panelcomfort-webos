#!/bin/sh
# Best-effort webOS input/picture-profile watcher.
# Uses only documented/public Luna queries and userland files. HDR metadata itself
# is not reliably exposed on all webOS TV firmware, so do not claim full HDR detection.
set -u
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
LOG="$ROOT_DIR/service.log"
# Input and pictureMode are returned as dimensions alongside ordinary picture settings.
QUERY='{"category":"picture","keys":["backlight","eyeComfortMode","input","pictureMode"]}'
log(){ printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }
get_context(){
  response=$(luna-send -n 1 -f 'luna://com.webos.settingsservice/getSystemSettings' "$QUERY" 2>/dev/null) || return 1
  printf '%s' "$response" | grep -Eq '"returnValue"[[:space:]]*:[[:space:]]*true' || return 1
  compact=$(printf '%s' "$response" | tr -d '\r\n ')
  input=$(printf '%s' "$compact" | grep -o '"input":"[^"]*"' | head -n 1 | sed 's/^"input":"//;s/"$//')
  mode=$(printf '%s' "$compact" | grep -o '"pictureMode":"[^"]*"' | head -n 1 | sed 's/^"pictureMode":"//;s/"$//')
  backlight=$(printf '%s' "$compact" | grep -o '"backlight":[0-9][0-9]*' | head -n 1 | sed 's/^[^:]*://')
  eye=$(printf '%s' "$compact" | grep -o '"eyeComfortMode":"[^"]*"' | head -n 1 | sed 's/^"eyeComfortMode":"//;s/"$//')
  # The active application ID commonly changes across HDMI input apps (e.g. hdmi1/hdmi2).
  # Keep it as an independent hint; official TV APIs do not guarantee an input/HDR event.
  app_response=$(luna-send -n 1 -f 'luna://com.webos.applicationManager/getForegroundAppInfo' '{}' 2>/dev/null || true)
  app_compact=$(printf '%s' "$app_response" | tr -d '\r\n ')
  app=$(printf '%s' "$app_compact" | grep -o '"appId":"[^"]*"' | head -n 1 | sed 's/^"appId":"//;s/"$//')
  printf '%s|%s|%s|%s|%s
' "${input:-unknown}" "${app:-unknown}" "${mode:-unknown}" "${backlight:-unknown}" "${eye:-unknown}"
}
last_context=''
last_drift_state=''
unsupported_logged=0
while :; do
  if [ ! -r "$CFG" ]; then sleep 5; continue; fi
  . "$CFG"
  if [ "${ENABLED:-1}" != 1 ] || [ "${PROFILE_PROTECTION_ENABLED:-1}" != 1 ]; then sleep 5; continue; fi
  context=$(get_context 2>/dev/null || true)
  if [ -z "$context" ]; then
    printf '%s
' 'Profile context unavailable; firmware query not supported or returned no data' > "$ROOT_DIR/profile-status.tmp" && mv "$ROOT_DIR/profile-status.tmp" "$ROOT_DIR/profile-status"
    if [ "$unsupported_logged" = 0 ]; then log 'Picture context query unavailable; continuing with the normal schedule only'; unsupported_logged=1; fi
    sleep 5; continue
  fi
  unsupported_logged=0
  input=$(printf '%s' "$context" | cut -d '|' -f 1)
  app=$(printf '%s' "$context" | cut -d '|' -f 2)
  mode=$(printf '%s' "$context" | cut -d '|' -f 3)
  actual_backlight=$(printf '%s' "$context" | cut -d '|' -f 4)
  actual_eye=$(printf '%s' "$context" | cut -d '|' -f 5)
  profile="$input|$app|$mode"
  printf '%s
' "input=$input; app=$app; pictureMode=$mode" > "$ROOT_DIR/profile-status.tmp" && mv "$ROOT_DIR/profile-status.tmp" "$ROOT_DIR/profile-status"
  if [ -z "$last_context" ]; then
    last_context=$profile
    log "Picture watcher active input=$input app=$app pictureMode=$mode"
  elif [ "$profile" != "$last_context" ]; then
    log "Input/picture context changed: $last_context -> $profile; reapplying scheduled values after profile settle"
    last_context=$profile
    last_drift_state=''
    sleep 1
    "$ROOT_DIR/daemon.sh" --once >> "$LOG" 2>&1 || true
    sleep 3
    "$ROOT_DIR/daemon.sh" --once >> "$LOG" 2>&1 || true
    sleep 5
    "$ROOT_DIR/daemon.sh" --once >> "$LOG" 2>&1 || true
  else
    # If the TV restores stored picture values after switching into an input/profile,
    # reapply only once for each observed mismatch to avoid hammering a stale readback.
    expected=$($ROOT_DIR/daemon.sh --calculate 2>/dev/null || true)
    set -- $expected
    want_backlight=${1:-}
    want_eye=${2:-}
    drift_reason=''
    if [ -n "$want_backlight" ] && [ "$actual_backlight" != unknown ] && [ "$actual_backlight" != "$want_backlight" ]; then
      drift_reason="backlight actual=$actual_backlight expected=$want_backlight"
    elif [ -n "$want_eye" ] && [ "$actual_eye" != unknown ] && [ "$actual_eye" != "$want_eye" ]; then
      drift_reason="eye comfort actual=$actual_eye expected=$want_eye"
    fi
    observed_state="$actual_backlight|$actual_eye"
    if [ -n "$drift_reason" ] && [ "$observed_state" != "$last_drift_state" ]; then
      log "Active profile $drift_reason; reapplying once for observed state"
      "$ROOT_DIR/daemon.sh" --once >> "$LOG" 2>&1 || true
      last_drift_state=$observed_state
    fi
  fi
  sleep 3
done
