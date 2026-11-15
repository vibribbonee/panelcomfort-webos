#!/bin/sh
set -eu
ROOT_DIR=/var/lib/webosbrew/panelcomfort
rm -f /var/lib/webosbrew/init.d/90-panelcomfort
if [ -f "$ROOT_DIR/ha-server.sh" ]; then "$ROOT_DIR/ha-server.sh" stop || true; fi
if [ -f "$ROOT_DIR/pid" ]; then
  pid="$(cat "$ROOT_DIR/pid" 2>/dev/null || true)"
  case "$pid" in *[!0-9]*|'') ;; *) if [ -r "/proc/$pid/cmdline" ] && tr '\000' ' ' < "/proc/$pid/cmdline" | grep -q 'daemon.sh'; then kill "$pid" 2>/dev/null || true; fi;; esac
  rm -f "$ROOT_DIR/pid"
fi
if [ -f "$ROOT_DIR/picture-watch.pid" ]; then
  pid="$(cat "$ROOT_DIR/picture-watch.pid" 2>/dev/null || true)"
  case "$pid" in *[!0-9]*|'') ;; *) if [ -r "/proc/$pid/cmdline" ] && tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'picture-watch.sh'; then kill "$pid" 2>/dev/null || true; fi;; esac
  rm -f "$ROOT_DIR/picture-watch.pid"
fi
printf 'AUTOSTART_REMOVED=1\n' 
