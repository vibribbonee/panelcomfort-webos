#!/bin/sh
# Retry the HyperHDR night/day target after TV boot without delaying the panel schedule.
set -u
ROOT_DIR=/var/lib/webosbrew/panelcomfort
CFG="$ROOT_DIR/config.env"
LOG="$ROOT_DIR/service.log"
LOCK="$ROOT_DIR/hyperhdr-retry.lock"
[ -r "$CFG" ] || exit 0
if ! mkdir "$LOCK" 2>/dev/null; then
  oldpid=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null && [ -r "/proc/$oldpid/cmdline" ] && tr '\000' ' ' < "/proc/$oldpid/cmdline" 2>/dev/null | grep -q 'hyperhdr-retry.sh'; then
    exit 0
  fi
  # The TV may have rebooted while the retry worker owned the lock directory.
  # Recover stale locks instead of suppressing every future retry indefinitely.
  rm -f "$LOCK/pid" 2>/dev/null || true
  rmdir "$LOCK" 2>/dev/null || true
  mkdir "$LOCK" 2>/dev/null || exit 0
fi
printf '%s\n' "$$" > "$LOCK/pid"
cleanup(){ rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true; }
trap cleanup EXIT HUP INT TERM
log(){ printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }
attempt=1
while [ "$attempt" -le 18 ]; do
  [ -r "$CFG" ] || exit 0
  . "$CFG"
  [ "${HYPERHDR_ENABLED:-0}" = 1 ] || { log 'HyperHDR startup retry cancelled because HyperHDR is disabled'; exit 0; }
  values=$(sh "$ROOT_DIR/daemon.sh" --calculate 2>/dev/null || true)
  set -- $values
  target=${4:-0}
  if sh "$ROOT_DIR/hyperhdr.sh" apply "$target" >> "$LOG" 2>&1; then
    log "HyperHDR startup retry succeeded (attempt=$attempt brightness=$target)"
    exit 0
  fi
  attempt=$((attempt + 1))
  [ "$attempt" -le 18 ] && sleep 5
done
log 'HyperHDR still unavailable after startup retries; normal scheduler will continue retrying once per minute'
exit 0
