#!/bin/sh
set -eu
APP_ID=com.webosbrew.panelcomfort
APP_DIR="/media/developer/apps/usr/palm/applications/$APP_ID"
ROOT_DIR=/var/lib/webosbrew/panelcomfort
HOOK_DIR=/var/lib/webosbrew/init.d
HOOK="$HOOK_DIR/90-panelcomfort"
for f in daemon.sh apply-queue.sh start.sh ha-server.sh panelcomfort-httpd.js ssdp-broadcast.sh hyperhdr.sh hyperhdr-retry.sh picture-watch.sh panelcomfort.cgi panelcomfort-ha.cgi panelcomfort-discovery.cgi panelcomfort-web.cgi panelcomfort-health.cgi default.env update-root.sh remove-root.sh; do
  if [ ! -r "$APP_DIR/scripts/$f" ]; then echo "ERROR=PanelComfort app file missing: $f"; exit 1; fi
done
mkdir -p "$ROOT_DIR" "$HOOK_DIR"
for f in daemon.sh apply-queue.sh start.sh ha-server.sh panelcomfort-httpd.js ssdp-broadcast.sh hyperhdr.sh hyperhdr-retry.sh picture-watch.sh panelcomfort.cgi panelcomfort-ha.cgi panelcomfort-discovery.cgi panelcomfort-web.cgi panelcomfort-health.cgi default.env install-root.sh remove-root.sh update-root.sh; do cp "$APP_DIR/scripts/$f" "$ROOT_DIR/$f"; done
chmod 700 "$ROOT_DIR/daemon.sh" "$ROOT_DIR/apply-queue.sh" "$ROOT_DIR/start.sh" "$ROOT_DIR/ha-server.sh" "$ROOT_DIR/panelcomfort-httpd.js" "$ROOT_DIR/ssdp-broadcast.sh" "$ROOT_DIR/hyperhdr.sh" "$ROOT_DIR/hyperhdr-retry.sh" "$ROOT_DIR/picture-watch.sh" "$ROOT_DIR/update-root.sh" "$ROOT_DIR/panelcomfort.cgi" "$ROOT_DIR/panelcomfort-ha.cgi" "$ROOT_DIR/panelcomfort-discovery.cgi" "$ROOT_DIR/panelcomfort-web.cgi" "$ROOT_DIR/panelcomfort-health.cgi"
chmod 755 "$ROOT_DIR/install-root.sh" "$ROOT_DIR/remove-root.sh"
if [ ! -f "$ROOT_DIR/config.env" ]; then cp "$ROOT_DIR/default.env" "$ROOT_DIR/config.env"; fi
if grep -q "^SHORTCUT_KEY=" "$ROOT_DIR/config.env"; then sed '/^SHORTCUT_KEY=/d' "$ROOT_DIR/config.env" > "$ROOT_DIR/config.env.tmp" && mv "$ROOT_DIR/config.env.tmp" "$ROOT_DIR/config.env"; fi
ensure_line(){ key=$1; value=$2; if ! grep -q "^${key}=" "$ROOT_DIR/config.env"; then printf '%s=%s\n' "$key" "$value" >> "$ROOT_DIR/config.env"; fi; }
ensure_line FADE_METHOD duration
ensure_line FADE_CURVE smooth
ensure_line HA_BRIGHTNESS_OFFSET 0
ensure_line HA_AMBIENT_LUX ''
ensure_line HA_AMBIENT_LUX_UPDATED 0
ensure_line AMBIENT_LUX_MIN 5
ensure_line AMBIENT_LUX_MAX 500
ensure_line LUX_STABILITY 10
ensure_line AMBIENT_BRIGHTNESS_OFFSET 0
ensure_line HYPERHDR_DARK_CURVE 0
ensure_line DIM_MODE fixed
ensure_line DIM_START 21:00
ensure_line DIM_DURATION 60
ensure_line UP_MODE fixed
ensure_line UNDIM_START 06:30
ensure_line UNDIM_DURATION 45
ensure_line EYE_TIMING linked
ensure_line EYE_ENABLED 1
ensure_line HA_EYE_COMFORT_OVERRIDE dynamic
ensure_line EYE_LUX_THRESHOLD 50
ensure_line EYE_START 21:30
ensure_line EYE_END 06:30
ensure_line SUNSET_LAT ''
ensure_line SUNSET_LON ''
ensure_line SUNSET_OFFSET -20
ensure_line EYE_START_OFFSET 15
ensure_line EYE_END_OFFSET 0
ensure_line SUNRISE_OFFSET 0
ensure_line PROFILE_PROTECTION_ENABLED 1
ensure_line WEB_UI_ENABLED 0
ensure_line HA_API_ENABLED 0
ensure_line HA_API_PORT 8765
ensure_line HA_DEVICE_ID ''
ensure_line WEBHOOK_ENABLED 0
ensure_line WEBHOOK_TOKEN ''
ensure_line WEBHOOK_HOST ''
ensure_line HYPERHDR_ENABLED 0
ensure_line HYPERHDR_HOST 127.0.0.1
ensure_line HYPERHDR_PORT auto
ensure_line HYPERHDR_TOKEN ''
ensure_line HYPERHDR_INSTANCE_IDS all
ensure_line HYPERHDR_MIN_BRIGHTNESS 12
ensure_line HYPERHDR_MAX_BRIGHTNESS 60
ensure_line MOVIE_BRIGHTNESS_ENABLED 0
ensure_line MOVIE_BRIGHTNESS 80
if ! grep -Eq '^WEBHOOK_TOKEN=[a-fA-F0-9]{8}$' "$ROOT_DIR/config.env"; then
  token=$(od -An -N4 -tx1 /dev/urandom | tr -d '[:space:]' | cut -c1-8)
  if grep -q '^WEBHOOK_TOKEN=' "$ROOT_DIR/config.env"; then sed "s/^WEBHOOK_TOKEN=.*/WEBHOOK_TOKEN=$token/" "$ROOT_DIR/config.env" > "$ROOT_DIR/config.env.tmp" && mv "$ROOT_DIR/config.env.tmp" "$ROOT_DIR/config.env"; else printf 'WEBHOOK_TOKEN=%s\n' "$token" >> "$ROOT_DIR/config.env"; fi
fi
if ! grep -Eq '^HA_DEVICE_ID=[a-fA-F0-9]{24}$' "$ROOT_DIR/config.env"; then
  device_id=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
  if grep -q '^HA_DEVICE_ID=' "$ROOT_DIR/config.env"; then sed "s/^HA_DEVICE_ID=.*/HA_DEVICE_ID=$device_id/" "$ROOT_DIR/config.env" > "$ROOT_DIR/config.env.tmp" && mv "$ROOT_DIR/config.env.tmp" "$ROOT_DIR/config.env"; else printf 'HA_DEVICE_ID=%s\n' "$device_id" >> "$ROOT_DIR/config.env"; fi
fi
chmod 600 "$ROOT_DIR/config.env"
mkdir -p "$ROOT_DIR/web-ui"
if [ -d "$APP_DIR/web-ui" ]; then cp -R "$APP_DIR/web-ui/." "$ROOT_DIR/web-ui/"; fi
chmod 700 "$ROOT_DIR/panelcomfort-web.cgi"
printf '0.3.23\n' > "$ROOT_DIR/service-version"
cat > "$HOOK" <<'HOOKSCRIPT'
#!/bin/sh
exec /var/lib/webosbrew/panelcomfort/start.sh
HOOKSCRIPT
chmod 755 "$HOOK"
"$ROOT_DIR/start.sh"
"$ROOT_DIR/daemon.sh" --once
printf 'INSTALLED=1\n'
