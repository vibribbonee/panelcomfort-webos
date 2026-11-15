# PanelComfort 0.3.20

[![Add to Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=vibribbonee&repository=panelcomfort-webos&category=integration)

PanelComfort is a rooted webOS app that schedules LG TV backlight and Eye Comfort settings, optionally scales HyperHDR output, and exposes separate local controls for Home Assistant, secret-link webhooks, and a browser dashboard.

## What's included in 0.3.20

- Ambient brightness and Dynamic Eye Comfort ignore lux samples saved before the current scheduler session. They use the configured time schedule until a new sample arrives, and fall back to that schedule after two minutes without fresh data.

- Home Assistant DHCP recovery scans the full shared LAN for subnets up to `/22`. This closes a gap where a bridged HA VM and TV could share a larger subnet but receive addresses in different `/24` blocks.
- Eye Comfort now has a **Time** mode, separate from the brightness calculation. It follows linked or custom clock times and ignores lux, so room lux can continue controlling brightness independently.

- App startup diagnostics now detect missing or non-executable installed root-service files even when the recorded service version matches. The app offers **Repair / update service** instead of attempting a start that cannot work; the updater also compares same-version installed files before skipping a repair.
- The browser dashboard avoids nullish-coalescing syntax so its JavaScript stays compatible with older engines.

## Carried forward in 0.3.20

- Movie Mode's custom slider remains the TV's actual backlight percentage. HyperHDR now maps that position within the configured TV night/day range to its own HyperHDR night/day range, preserving each output's configured relative brightness instead of sending both outputs the same number. TV app and browser previews show both targets.

- Home Assistant status sensors now share the existing cached status request instead of each starting separate TV CGI work during parallel polls. The HyperHDR Day Maximum entity starts at 1%, matching the TV API validation so HA cannot submit a value the TV rejects.

- Eye Comfort has **Dynamic / Time / On / Off** control. Dynamic turns it on at or below a configurable lux threshold when a fresh ambient reading is available, then falls back to its linked or custom schedule when readings are missing or stale. Time always follows that schedule and ignores lux. Movie Mode pauses Dynamic and Time; explicit On and Off overrides remain available.
- The Eye Comfort lux threshold is shared by the TV app, browser dashboard, and Home Assistant. The HA lux entity can drive Eye Comfort Dynamic even when the brightness calculation is set to time or solar mode; webhook and browser lux samples also work.

- Home Assistant now shares and briefly caches each TV status response across all entities, instead of launching a separate shell/API calculation for every setting during a poll. HA writes are serialized per TV, and overlapping changes report the latest saved value without falsely setting entities unavailable.
- The local Node HTTP service limits concurrent CGI work and queues bursts, protecting the TV from a pile-up of shell processes. The browser dashboard uses the full response from each save/action instead of immediately issuing a duplicate status request.

- Rapid Home Assistant, browser-dashboard, and webhook edits now write through a shared config lock and queue/coalesce screen applies. This prevents overlapping config temp files and keeps slow TV/HyperHDR calls out of HTTP requests, so clients stay responsive while the latest settings apply.
- Status reads use the cached TV sensor sample instead of opening a new webOS sensor subscription for every HA entity poll; actual applies still refresh the sensor.

- The browser dashboard now matches the TV app and Home Assistant for operational settings: lux mapping, ambient offset, manual Eye Comfort override, linked Eye Comfort offsets, solar offsets, HyperHDR enable and limits, and picture-profile protection.
- Home Assistant adds a Picture Profile Protection switch. All three interfaces now edit the same saved TV configuration for schedule, Movie Mode, Eye Comfort, sensor mapping, solar calculation, HyperHDR brightness, and profile protection.
- The browser dashboard keeps connection setup and service diagnostics in the TV app; its settings write through the same TV config and queue a coalesced apply.

- Home Assistant now exposes the brightness calculation and curve selectors, evening/morning triggers and start times, fade durations, Eye Comfort timing and override, schedule enable, sunrise/sunset offsets, brightness bounds, and screen apply status.
- Movie Mode's custom brightness uses the TV target as the reference and maps the room lights proportionally across their separate configured night/day bounds. HA slider changes write the saved TV config and queue an apply; disabling custom Movie Mode brightness returns each output to its scheduled daytime target.
- Home Assistant lux is optional. A selected illuminance sensor is forwarded when brightness uses **Home Assistant lux sensor** or Eye Comfort uses **Dynamic**; otherwise it is not needed.
- The HA 1.18.0 integration reacts to selected lux sensor state changes and forwards new readings promptly instead of waiting for the next 30-second poll. It still refreshes unchanged values periodically so the TV's lux sample stays fresh.
- Lux Stability defaults to 10 lx and is shared by the TV app, browser dashboard, and HA. It ignores small lux changes for brightness updates; Dynamic Eye Comfort also uses it as turn-off hysteresis. Set it to 0 to disable filtering.
- Webhook lux samples now use the same Lux Stability filtering and freshness handling as Home Assistant and browser samples.
- Ambient mode now has configurable **Ambient Lux Minimum** and **Ambient Lux Maximum** controls (defaults 5 lx and 500 lx) and an optional **Ambient Brightness Offset**. The lux bounds map room brightness between the configured night/day targets, and the offset adjusts both the TV and HyperHDR outputs. These settings are available in the TV app, Home Assistant, and browser dashboard.
- The Home Assistant lux sensor selector is explicitly optional. With fresh lux readings, evening and morning triggers do not affect brightness; the configured schedule is used only as a fallback when readings are missing or older than two minutes.
- The TV app's Movie Mode button no longer sends a duplicate HyperHDR adjustment after the scheduler has already applied it.
- Screen apply status distinguishes queued work from completed work. Rejected TV settings are recorded with their target and time in `apply-status` and `service.log`, while browser and HA writes can return as soon as the validated settings are saved.
- The Home Assistant integration scans for the stable TV identity after an address change. A DHCP reservation remains the most reliable way to keep the TV address fixed.

- Startup recovery for an installed service: opening the app checks status and restarts the existing root service if the enabled scheduler or configured local HTTP listener is stopped. It does not replace root scripts or alter settings; **Repair / update service** remains an explicit action.
- Older-webOS-compatible JavaScript syntax. One absent optional button must not stop registration of other click handlers.
- Fixed time-based fades with 12 curves, solar-elevation mode, optional Home Assistant or webhook illuminance input, and a model-dependent LG luminance-sensor path. Sensor fallback is automatic if readings are unavailable or stale.
- Movie Override applies the configured Movie Mode TV target with the HyperHDR target mapped through each output's own night/day range (or each output's daytime target when custom brightness is disabled) and pauses scheduled Eye Comfort while active. A forced Eye Comfort mode from Home Assistant takes priority. The scheduler resumes when override is turned off.
- HyperHDR v22 `scaleOutput` support. Instance IDs are discovered from serverinfo; each selected running instance is selected through HyperHDR's `instance/switchTo` API and adjusted in the same HTTP request. `all` fails closed if running instance IDs cannot be determined.
- A working root page at port `8765` that explains which local endpoints are enabled and links to health/discovery diagnostics.
- The read-only service page now listens on port `8765` after service setup even when Home Assistant, webhooks, and the browser dashboard are all disabled. Those control features remain opt-in.
- The local HTTP and CGI service uses a small dependency-free Node.js server, since some webOS firmware builds omit BusyBox HTTPD. The root installer and service updater copy the server script along with the shell scripts.
- HyperHDR instance selection uses remote-friendly checkboxes for all running instances or individual IDs, with manual ID entry kept as a fallback.
- A startup retry worker reapplies the current HyperHDR target during the first 90 seconds after a cold boot, without delaying the TV backlight change.
- Manual Home Assistant pairing, discovery endpoint diagnostics, DHCP rediscovery, target/phase entities, a bounded brightness offset, and optional lux-sensor forwarding.
- Eight-hex-character secret links for Movie Mode on/off/toggle, status, and ambient-lux samples. The browser dashboard is **opt-in for fresh installs** because it can change TV settings.
- `H:MM` durations and offsets (for example `1:05` = 65 minutes), a sunset-shaped curve preview, and a browser-dashboard Eye Comfort timing selector that preserves linked/custom mode.

## Tested hardware

Hardware tested on a rooted LG UP78 43-inch 4K Smart UHD TV (43UP78006LB) running webOS 6.3.2-425.

## Installation / upgrade

For TV installation, open **Homebrew Channel → Settings → Add repository** and enter [the webOS catalog](https://raw.githubusercontent.com/vibribbonee/TheVibeCollection/main/repo.json). You can also download the IPKs from [GitHub Releases](https://github.com/vibribbonee/panelcomfort-webos/releases).

1. Install `com.webosbrew.panelcomfort_0.3.20_all.ipk` over the existing app using your existing rooted webOS installation path; do not uninstall first unless you intentionally want to remove the app state.
2. Open PanelComfort and press **Repair / update service** once. The app detects the older root-script version and copies updated scripts into the root service directory. Installing the IPK alone updates the app files, while the root service has a separate installed copy.
3. Review the settings that are enabled, then press **Save & apply**. The main scheduler is independent from whether the app remains open.
4. In **Ambient LEDs → Connection settings**, run the HyperHDR connection test and use the checkboxes to select all or individual running instances, then save. HyperHDR scale is distinct from the TV's own backlight target.
5. For Home Assistant, enable the HA API and save. Replace `/config/custom_components/panelcomfort` with the `custom_components/panelcomfort` folder from this repository, then restart Home Assistant. Try discovery first; if it doesn't appear, add the integration manually with the TV's current LAN IPv4 address and port (default `8765`). A successful health check only proves the HTTP listener; the HA discovery endpoint is separate.
6. Webhooks and the browser dashboard are separately configurable. The dashboard is disabled by default for fresh installs; enable it only if you need it and save the setting.

## Important behaviour

- Schedules are evaluated against the TV's local clock. A 19:00 start and 120-minute linear fade is halfway through at 20:00 even if the TV was powered on at that time; power-on does not restart the fade.
- The solar mode maps calculated solar elevation to brightness using coordinates and the current day. It does not know weather or the actual light in the room. A fade curve still shapes the response, but a fixed duration is bypassed.
- Ambient mode maps readings between **Ambient Lux Minimum** (default 5 lx) and **Ambient Lux Maximum** (default 500 lx) using the selected curve. Values below/above those limits clamp to the configured night/day targets. **Ambient Brightness Offset** shifts both TV and HyperHDR targets by up to ±30 percentage points. Fresh readings bypass the evening and morning brightness triggers; if readings are missing or older than two minutes, the clock schedule is used as a fallback. The HA lux entity is always optional; select one only if you want Home Assistant to supply Ambient-mode readings. A webhook or browser dashboard can provide samples without it.
- To use Home Assistant lux, choose **Home Assistant lux sensor** under the HA device's **Brightness Calculation** selector, then select an illuminance entity from the integration options. The entity is optional for all other methods. Webhooks and the browser dashboard can also provide ambient readings without Home Assistant.
- Built-in TV luminance sensor access depends on model and firmware. A failed sensor test is a capability limitation, not evidence that the TV has no ambient sensor at all; do not select this mode unless it returns readings.
- Input and picture-profile protection is **best effort**. Firmware may omit the fields or HDR metadata required to reliably detect an HDMI / picture-mode transition; the normal schedule continues if those APIs are unavailable.
- Backlight and HyperHDR targets are calculated values. Home Assistant does not receive an independently measured physical panel-brightness reading.

## Network and security

- Local service port: `8765` by default. Its read-only status page is available after service setup; Home Assistant, webhook, and browser-dashboard controls are separately enabled and remain off by default.
- Home Assistant and webhook endpoints accept private IPv4 source addresses without user authentication. This is a coarse network boundary, not authentication and not a guarantee of same-/24 access. Guest-device isolation, router ACLs, or a trusted VLAN are recommended; **never port-forward this port to the internet**.
- Webhook URLs have an eight-hex-character secret (32 bits of entropy, by request). Treat these links as passwords; do not publish them or expose them outside a trusted LAN.
- The optional browser dashboard has no login. It is disabled by default for fresh installs and should only be enabled on a trusted home network.
- HyperHDR JSON-RPC also needs to be kept on the local network; use its API token if configured by your installation.

## Diagnostics

- **TV app → Home Assistant → Test endpoint** checks service status and the TV-local HTTP health URL, and displays recent listener logs. If the listener fails, `httpd.log` records the Node server startup error.
- From another trusted LAN device, `http://TV-IP:8765/` opens the PanelComfort status page after the root service is installed. `http://TV-IP:8765/cgi-bin/panelcomfort-health.cgi` tests whether the server responds. `http://TV-IP:8765/cgi-bin/panelcomfort-discovery.cgi` only succeeds when the Home Assistant API is enabled. If the browser dashboard is enabled, `/` opens that dashboard instead. This port is separate from HyperHDR's web page, usually at port `8090`.
- The webhook token path is shown by the app; verify the actual action URL (`?movie=on`, `?movie=off`, `?movie=toggle`, `?action=status`, or `?ambient_lux=NUMBER`). Opening `/` is not a control action.
- Inspect `/var/lib/webosbrew/panelcomfort/service.log`, `httpd.log`, and `ssdp.log` from the root shell when an action fails. Do not post webhook tokens or private details in logs.
- If HyperHDR is not responding, test its JSON-RPC connection before changing the host/port. Your output scale uses `scaleOutput` (for example 0.32 means 32%), not the legacy `brightness` adjustment field.

## Build and local tests

Build the IPK with `./build-ipk.sh` (optionally pass an output path). The builder writes a standard ar container directly, so it does not require root ownership changes or the Xcode `ar` utility. The outer members use non-epoch timestamps and `0:1001` ownership metadata; inner payloads use USTAR headers, explicit root ownership metadata, and gzip streams without timestamps so macOS provenance data is not included.

Run the offline test suite with `./tests/run-tests.sh`. The current suite has 27 tests covering shell/JavaScript/Python/JSON syntax; HTML IDs and tab wiring; release-version consistency; schedule timing and all fade curves; ambient-data freshness; webhook and Home Assistant CGI validation; SSDP identity formatting; default-off dashboard behaviour; private config permissions after CGI writes; browser-dashboard schedule save and linked/custom Eye Comfort timing; and HyperHDR multi-instance JSON requests against a stub API. It also builds a temporary IPK and checks its archive metadata and included files.

The offline suite uses stubs for TV APIs and network services. Hardware testing is listed above. Model-specific Luna APIs, multicast, the built-in luminance sensor, and the root boot hook can vary with firmware.

## Contributing

Pull requests are welcome. Describe what changed and how you tested it.

## AI disclosure

OpenAI Codex assisted with development, testing, and documentation.
