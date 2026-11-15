# PanelComfort — project audit and QA report

## Current review for 0.3.17

- Fixed the repair-button dead end: app diagnostics now check for missing or non-executable installed service files even when the version file says current. A damaged install stays repairable instead of retrying a missing `start.sh` with the repair control hidden.
- The root updater no longer trusts the version string by itself. For a same-version install, it compares the copied scripts and restores missing, changed, or non-executable files.
- Removed nullish-coalescing operators from the LAN dashboard JavaScript to keep it usable on older browser engines.
- Corrected the offline test fixtures to provide the apply-queue dependency. The IPK test now reads the ar headers itself, avoiding the local Xcode `ar` license gate while checking member metadata and tar contents.
- Removed the unreferenced `custom_components 2` directory after confirming it was an exact duplicate of the kept Home Assistant component copy.
- Built the 0.3.17 IPK and ran the 27-test offline suite. It covers source syntax, the scheduler, CGI validation and persistence, dashboard saves, HyperHDR multi-instance behavior, and package structure. No live TV or Home Assistant runtime was available.

## Carried forward from 0.3.16

- Fixed a Home Assistant range mismatch: **HyperHDR Day Maximum** previously allowed 0%, while the TV API requires at least 1%. The HA number now matches the API.
- Routed the five HA status sensors and Eye Comfort binary sensor through the shared status cache. Parallel HA polls can reuse one TV status response rather than starting six additional CGI processes.
- Movie Mode's custom slider continues to represent actual TV backlight percent, while the HyperHDR target follows the same relative position across its own night/day bounds. The TV and browser previews identify both targets.
- The HA 1.15.0 integration exposes the shared Lux Stability setting and filters small changes before forwarding them; unchanged readings still refresh periodically to keep the TV's sample fresh.
- Lux Stability defaults to 10 lx, can be set from 0 to 1000 lx in the TV app, browser dashboard, or HA, and applies the same deadband to lux-driven brightness updates. Dynamic Eye Comfort turns on at its configured threshold and remains on until lux rises above threshold plus Lux Stability.
- Webhook lux samples now use that same deadband, and refresh the sample timestamp without queuing a screen change when the reading remains inside the deadband.
- Built the 0.3.16 IPK. Static syntax, package metadata, ZIP contents, and version consistency were checked; the offline regression suite and live TV / Home Assistant behavior were not checked in that review.

### Remaining design cleanup

- The HA **Eye Comfort Mode** select and **Eye Comfort** switch both write `HA_EYE_COMFORT_OVERRIDE`. The select preserves Dynamic / On / Off; the switch is a quick force-on/force-off control. Make that relationship clearer in the entity name or description so users know using the switch exits Dynamic mode.
- HA keeps mode-specific settings visible all the time. Ambient lux bounds matter in Ambient mode; solar coordinates and offsets matter only for solar-based triggers/calculation; Eye Comfort schedule times matter when Eye Comfort follows a schedule. Grouping or clearly describing these dependencies would reduce dashboard clutter without removing the settings.
- Dynamic Eye Comfort uses Lux Stability as its turn-off hysteresis. A separate minimum dwell time could be added if real sensor behavior shows it is needed; this release keeps the control to one understandable setting.
- HA entity classes still repeat host, timeout, request, and rediscovery code across platforms. A shared API client or `DataUpdateCoordinator` would centralize address recovery and updates further; the current short-lived shared cache and write lock are a lower-risk interim improvement.

## Follow-up fix in 0.3.4

- The user installed 0.3.3 and confirmed the TV has no BusyBox `httpd` applet, but does have `/usr/bin/node` and `/usr/sbin/lighttpd`. HyperHDR serves its page from a native Qt HTTP server embedded in its own process; PanelComfort cannot borrow that server.
- Replaced the external `httpd` dependency with a small Node.js HTTP/CGI bridge using core Node modules. It only maps known CGI endpoints, serves static files from the PanelComfort webroot, and preserves the private-IPv4 check.
- Fixed service installation and repair to copy `panelcomfort-httpd.js` into the root service directory; the earlier Node listener wiring omitted this copy. Built the 0.3.4 IPK and inspected its package metadata and payload. Tests were not run, and the 0.3.4 listener still needs installation and confirmation on the TV.

## Follow-up fixes in 0.3.2

- Replaced the primary HyperHDR instance-ID text field with remote-friendly checkboxes for all running instances or individual instances. Manual ID entry remains under a collapsed fallback section.
- Kept a read-only service page and health endpoint available on port `8765` after service setup even when Home Assistant, webhooks, and the browser dashboard are all disabled. Control endpoints remain opt-in.
- Compared the supplied `hyperion-webos` project and its linked PicCap UI. The backend project is a local capture process; PicCap is the installed TV frontend that ships and controls it. Neither describes a browser dashboard on `8765`, so PanelComfort's own listener and opt-in dashboard behavior are independent.
- Built the 0.3.2 IPK. The test suite was not run, and no physical TV or browser-on-LAN check was available for this follow-up.

## Previous follow-up fixes in 0.3.1

- Fixed HyperHDR multi-instance scaling: each API session now switches to the selected running instance and sends its `scaleOutput` adjustment in the same repeated-request call. This addresses the case where the primary LEDs changed but separate side-light instances did not.
- Added a useful root page on port `8765` with the health link and conditional Home Assistant discovery link. It also explains that HyperHDR's web UI is a separate service, typically on port `8090`.
- Bumped the app and root-script version so the TV prompts **Repair / update service** after the IPK is installed; this copies the new scripts to their separate root-service location.

The user installed 0.3.1 and confirmed that the separate HyperHDR side-light instances now respond. The user later installed 0.3.2 and supplied the listener failure recorded above. The test suite was not run for the 0.3.2 follow-up.

## Scope

Reviewed the webOS app, root service lifecycle, scheduler, optional BusyBox HTTP/CGI endpoints, HyperHDR integration, browser dashboard, Home Assistant custom integration, package builder, documentation and offline tests. The aim was to reduce regressions from previous releases and make failure states diagnosable rather than to claim unperformed physical-device testing.

## Fixes and cleanup in this release

- **TV UI resilience:** checked every static HTML ID referenced by the TV app and checked tab-to-panel pairing. Optional click targets are bound defensively so one missing element should not abort registration of the other controls. JavaScript is screened for syntax/features known to be risky on older embedded WebKit engines.
- **Remote navigation and compact layouts:** added four-way focus movement and focus-aware scrolling for arrow-key remotes. Fixed the narrow-view tab bar so it uses an actual two-column grid and stops sticking over the settings panel when it wraps.
- **Refresh and service recovery:** opening the app checks status and restarts the installed root service when an enabled scheduler or configured HTTP listener is stopped. It does not update root scripts or settings; Repair remains explicit. Refresh polling does not overwrite dirty/unsaved settings.
- **Schedule behaviour:** tests cover a fade that started before the TV woke (19:00 start + 120 minutes means the 20:00 target is halfway), all 12 monotonic fade curves, end-of-fade, morning transition, midnight crossover, Movie Override, bounded solar output and ambient-reading freshness/fallback.
- **Dashboard consistency:** the dashboard now has an explicit linked/custom Eye Comfort timing selector. The CGI validates and saves that choice and reports it back to the UI instead of silently forcing `EYE_TIMING=custom` on every save. The dashboard tracks dirty fields to avoid polling over edits.
- **Config-file hygiene:** CGI processes use a private umask and the dashboard setting writer secures replaced configuration files with mode `0600`. The browser dashboard remains opt-in by default; installs only enable it when an existing explicit value or user setting says so.
- **Root-script maintenance:** the updater and service scripts were checked for consistent version reporting and required-file installation. The picture watcher requests the input/picture fields it then inspects; this remains best effort because firmware can omit those values.
- **Home Assistant:** reviewed config flow, SSDP discovery, manual host/port pairing, config-entry migration, entity polling, bounded brightness offset, illuminance forwarding and DHCP rediscovery. Setup docs now distinguish a working HTTP health endpoint from an enabled HA discovery/control endpoint.
- **HyperHDR:** the existing stub test now checks that each running instance is switched to before its `scaleOutput` adjustment; “all” fails closed when the running instance IDs cannot be determined. The script reports the targeted instances rather than claiming hardware readback. This test was not run for the 0.3.1 follow-up.
- **IPK builder:** fixed normalization of relative output paths, writes the standard three-member ar container without requiring privileged `chown` or Xcode's `ar`, sets ordinary timestamps and expected ownership fields, and emits GNU-compatible USTAR payloads with timestamp-free gzip streams to avoid macOS PAX provenance metadata.
- **Docs and cleanup:** removed unused helper/dead code, removed test-generated bytecode before packaging, and documented limitations/security assumptions.

## Offline validation results

The 27-test run below was repeated against the 0.3.17 source. It is offline and does not replace validation on a physical TV.

Command: `./tests/run-tests.sh`

Result: **27 tests passed**. They cover:

- Node syntax checks for TV app and browser dashboard JS
- POSIX shell parse checks for service, CGI and build scripts
- JSON parsing and Python compilation for the Home Assistant integration
- HTML ID uniqueness/references, defensive click bindings and tab/panel pairing
- release-version consistency and old-WebKit syntax guardrails
- duration parsing/formatting and bounded monotonic preview curves
- temporary IPK construction and non-epoch archive metadata
- default-off dashboard and same-origin guard
- browser CGI save round-trip for linked Eye Comfort timing and mode `0600` config permissions
- webhook Movie Mode and ambient-lux updates, input validation and private-client rejection
- HA status/offset validation and stable discovery identity
- mock HyperHDR instance detection/application for IDs `0` and `3`, and fail-closed behaviour
- scheduler timing, curve monotonicity, midnight rollover, Movie Override, solar bounds, and stale/recent sensor handling

The initial 0.3.0 IPK was rejected by the TV because macOS tar included PAX provenance metadata. The builder was corrected and the user confirmed that the rebuilt 0.3.0 package installed. Versions 0.3.1 and 0.3.2 carry the same USTAR/gzip builder and the follow-up fixes described above.

## Not verified here

This environment did not have the Home Assistant Core runtime or the TV's Luna/root execution service. Therefore the following remain **physical-device/integration tests**, not claimed as passed:

1. webOS installer acceptance and cold launch on the LG 43UP78006LB.
2. `luna-send` permission/service calls against the exact firmware, including backlight, Eye Comfort, input/profile protection and built-in illuminance sensor.
3. boot-hook persistence and root service start after actual TV power cycles.
4. HyperHDR v22 response semantics on the live TV and actual LED changes on both selected instances.
5. LAN HTTP reachability from Home Assistant, router isolation/firewall behaviour, and SSDP multicast delivery.
6. End-to-end Home Assistant config flow/entity setup and live lux sensor forwarding.
7. Real-world sunrise/sunset timing and whether the selected fade curve matches the user's preferred perception.

## Recommended user-facing improvements after device validation

- A guided first-run/diagnostics view that separately reports: root channel reachable, boot hook installed, scheduler running, HTTP listener reachable, HA API enabled, webhook active, HyperHDR reachable, and which instances acknowledged the last adjustment.
- A pre-update backup/restore button for `config.env` and a one-click diagnostic bundle that automatically redacts webhook and HyperHDR secrets.
- A per-instance HyperHDR preview/test action (for example briefly set 20%, restore prior target) before enabling scheduled writes.
- A distinction everywhere between *target* brightness and actual hardware readback; the current sensor is not available on every model/firmware.
- A testable recovery mode for root-service updates that preserves configuration and offers rollback if the updated daemon does not start.
- Optional TLS/authentication for browser dashboard / control API if use beyond a trusted LAN is ever required. Do not port-forward the current port; the eight-hex-character webhook secret is intentionally short and provides only 32 bits of entropy.

## Assessment

The project is in a better state for continued maintenance because known regression classes now have tests and the package is reproducibly buildable. **This is a source-level and mocked-service audit, not a statement that every feature has been confirmed on a physical television.** Install on the device only after keeping a copy of the last known working IPK and, preferably, the root config directory.
