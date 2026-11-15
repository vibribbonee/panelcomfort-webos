#!/bin/sh
set -eu
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
[ -r "$CFG" ] || exit 0
. "$CFG"
stop_owned(){
  file=$1; pattern=$2
  if [ -f "$file" ]; then
    p=$(cat "$file" 2>/dev/null || true)
    case "$p" in ''|*[!0-9]*) ;; *) if [ -r "/proc/$p/cmdline" ] && tr '\000' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -q "$pattern"; then kill "$p" 2>/dev/null || true; fi;; esac
    rm -f "$file"
  fi
}
stop_owned "$ROOT_DIR/pid" 'daemon.sh'
stop_owned "$ROOT_DIR/picture-watch.pid" 'picture-watch.sh'
if [ "${ENABLED:-1}" = 1 ]; then
  # Do not trust a persisted HA lux sample across a scheduler restart. If HA is
  # still reconnecting, use the clock schedule until a fresh sample arrives.
  if now=$(date +%s 2>/dev/null) && [ -n "$now" ]; then
    printf '%s\n' "$now" > "$ROOT_DIR/lux-session-start.tmp" && chmod 600 "$ROOT_DIR/lux-session-start.tmp" && mv "$ROOT_DIR/lux-session-start.tmp" "$ROOT_DIR/lux-session-start" || rm -f "$ROOT_DIR/lux-session-start.tmp"
  fi
  nohup "$ROOT_DIR/daemon.sh" >/tmp/panelcomfort.log 2>&1 &
  echo $! > "$ROOT_DIR/pid"
  if [ "${PROFILE_PROTECTION_ENABLED:-1}" = 1 ]; then
    nohup "$ROOT_DIR/picture-watch.sh" >/tmp/panelcomfort-picture-watch.log 2>&1 &
    echo $! > "$ROOT_DIR/picture-watch.pid"
  else
    rm -f "$ROOT_DIR/profile-status"
  fi
else
  "$ROOT_DIR/daemon.sh" --once || true
  rm -f "$ROOT_DIR/profile-status"
fi
# The read-only service page is always available; control endpoints remain optional.
# Listener failures never stop TV dimming.
if [ -x "$ROOT_DIR/ha-server.sh" ]; then
  "$ROOT_DIR/ha-server.sh" restart || printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" 'Local control listener failed to start; check httpd.log' >> "$ROOT_DIR/service.log"
fi
exit 0
