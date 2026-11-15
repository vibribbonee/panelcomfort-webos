#!/bin/sh
# Coalesce bursts of UI/HA updates into one or two applies, outside the HTTP request.
ROOT_DIR=/var/lib/webosbrew/panelcomfort
LOG="$ROOT_DIR/service.log"
PENDING="$ROOT_DIR/apply-queue.pending"
LOCK="$ROOT_DIR/apply-queue.lock"

cleanup(){ rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true; }

if [ "${1:-}" = --worker ]; then
  if ! mkdir "$LOCK" 2>/dev/null; then
    owner=$(cat "$LOCK/pid" 2>/dev/null || true)
    case "$owner" in
      ''|*[!0-9]*) sleep 1; owner=$(cat "$LOCK/pid" 2>/dev/null || true);;
    esac
    case "$owner" in
      ''|*[!0-9]*) rm -rf "$LOCK" 2>/dev/null || true; exec "$0" --worker;;
      *)
        if ! kill -0 "$owner" 2>/dev/null || { [ -r "/proc/$owner/cmdline" ] && ! tr '\000' ' ' < "/proc/$owner/cmdline" 2>/dev/null | grep -q 'apply-queue.sh'; }; then
          rm -rf "$LOCK" 2>/dev/null || true
          exec "$0" --worker
        fi
        exit 0 ;;
    esac
  fi
  printf '%s\n' "$$" > "$LOCK/pid"
  trap cleanup 0
  trap 'cleanup; exit 1' HUP INT TERM
  while :; do
    # Let a slider burst finish, then apply the latest saved config once.
    sleep 0.35
    [ -f "$PENDING" ] || break
    rm -f "$PENDING"
    if ! "$ROOT_DIR/daemon.sh" --once >> "$LOG" 2>&1; then
      printf '%s PanelComfort apply queue worker reported an apply error\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"
    fi
  done
  cleanup
  trap - 0 HUP INT TERM
  # Close the race where a request arrived as the worker was releasing its lock.
  [ ! -f "$PENDING" ] || exec "$0" --worker
  exit 0
fi

touch "$PENDING" || exit 1
if [ -d "$LOCK" ]; then
  owner=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -z "$owner" ]; then sleep 1; owner=$(cat "$LOCK/pid" 2>/dev/null || true); fi
  case "$owner" in
    ''|*[!0-9]*) rm -rf "$LOCK" 2>/dev/null || true ;;
    *)
      if kill -0 "$owner" 2>/dev/null && { [ ! -r "/proc/$owner/cmdline" ] || tr '\000' ' ' < "/proc/$owner/cmdline" 2>/dev/null | grep -q 'apply-queue.sh'; }; then exit 0; fi
      rm -rf "$LOCK" 2>/dev/null || true ;;
  esac
fi
nohup "$0" --worker >/dev/null 2>&1 &
exit 0
