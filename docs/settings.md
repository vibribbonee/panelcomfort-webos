# PanelComfort settings and diagnostics

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
