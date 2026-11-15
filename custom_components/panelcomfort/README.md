# PanelComfort Home Assistant integration 1.18.0

Connects Home Assistant to the rooted LG webOS PanelComfort scheduler. The TV and integration must both be updated for the new controls.

## Install

1. Copy `custom_components/panelcomfort` from the integration ZIP into Home Assistant's `/config/custom_components/panelcomfort`.
2. Restart Home Assistant.
3. In PanelComfort on the TV, open **Home Assistant**, enable its endpoint, press **Save & apply**, and keep port `8765` unless it conflicts.
4. Accept the SSDP discovery prompt if it appears. Otherwise, use **Settings → Devices & services → Add integration → PanelComfort**. The integration tries SSDP and a bounded local-subnet scan before asking for an address.

## Home Assistant controls

The device page separates editable settings from the main switches and live sensors. The browser dashboard and TV app edit the same schedule, Eye Comfort, ambient mapping, HyperHDR brightness, solar, and picture-profile settings.

- **Movie Mode** applies the Movie Mode targets immediately.
- **Movie Mode Brightness** is the TV's actual backlight percentage. HyperHDR maps the same position between the TV's night/day limits onto its own configured night/day limits, so both outputs reach their corresponding endpoints together. Changing the slider enables the custom target; it applies immediately when Movie Mode is active and is used the next time Movie Mode starts. **Custom Movie Brightness** can disable that target, returning each output to its own daytime schedule target.
- **Brightness Schedule** enables or pauses the scheduled day/night calculation.
- **Eye Comfort Mode** offers **Dynamic**, **Time**, **On**, and **Off**. Dynamic turns Eye Comfort on at or below **Eye Comfort Lux Threshold** when a fresh reading is available; otherwise it follows linked or custom schedule timing. Time always follows that timing and ignores lux, independently of the brightness calculation. Movie Mode pauses Dynamic and Time. On and Off are explicit overrides, including during Movie Mode. The direct **Eye Comfort** switch selects On or Off, and **Eye Comfort Schedule** enables or disables schedule timing.
- **Eye Comfort Lux Threshold** defaults to 50 lx and accepts 0–200,000 lx. The optional HA illuminance entity is forwarded whenever Eye Comfort uses Dynamic mode, even if brightness uses a different calculation method. Webhook and browser lux samples can also drive it. Time mode does not use lux for Eye Comfort.
- **Brightness Calculation** selects Time-based fade, Solar elevation, Home Assistant lux sensor, or TV built-in sensor. Related configuration entities include Fade Curve, evening/morning triggers and start times, fade durations, Eye Comfort timing and times, sunrise/sunset offsets, solar coordinates, and day/night bounds.
- **Ambient Lux Minimum** and **Ambient Lux Maximum** define the room-light range for Ambient mode (defaults 5 lx and 500 lx). At/below the minimum, the configured night screen/LED targets are used; at/above the maximum, their daytime targets are used. The selected fade curve shapes the response between them.
- **Lux Stability** defaults to 10 lx and ignores changes within that range of the last accepted reading, preventing small sensor fluctuations from triggering brightness updates. Dynamic Eye Comfort turns on at or below its configured threshold and stays on until lux rises above the threshold plus Lux Stability. Set Lux Stability to 0 to disable the deadband and hysteresis.
- **Ambient Brightness Offset** shifts both calculated screen and HyperHDR targets by −30 to +30 percentage points while fresh lux data is active. It defaults to 0. **Brightness Offset** remains the separate screen-only adjustment.
- **HyperHDR Control** enables or pauses LED brightness updates. HyperHDR night/day bounds remain independent and are used to map the Movie Mode TV target to the LEDs.
- **Picture Profile Protection** enables or pauses reapplication after picture-profile changes. Detection remains best effort on firmware that exposes the needed profile data.
- **Brightness Offset** adjusts the TV panel target by −30 to +30 percentage points. **Ambient Brightness Offset** is separate and adjusts both TV and HyperHDR targets only while fresh lux readings drive Ambient mode.
- **Backlight Target**, **HyperHDR Target**, **Schedule Phase**, **Ambient Illuminance**, and **Screen Apply Result** report calculated targets, current phase, the last lux sample, and whether webOS accepted the last screen-settings request.
- Status sensors share the same short-lived cached TV response as configuration entities, avoiding duplicate status CGI work during Home Assistant's parallel entity polls. HyperHDR Day Maximum now respects the TV API's 1% minimum.

The target sensors report calculated values, not independently measured physical panel or LED brightness. `Screen Apply Result: sent` means webOS accepted the settings request; it does not confirm when the panel visibly changes.

## Optional Home Assistant lux input

A lux sensor is optional in the integration options and is not required to set up or use PanelComfort. Choose an illuminance entity with device class `illuminance` and unit `lx` or `lux` if you select **Home Assistant lux sensor** for brightness or use **Dynamic** Eye Comfort. New sensor readings are forwarded as soon as Home Assistant reports a state change; unchanged readings are refreshed at least once per minute while connected to keep the TV sample fresh. While fresh lux readings are available, Ambient brightness ignores the evening and morning triggers and maps room illuminance through the configured lux bounds. Dynamic Eye Comfort turns on at or below its threshold and uses Lux Stability as its turn-off hysteresis. After a TV scheduler restart, the configured clock schedule remains active until a new lux sample arrives. If data is missing or older than two minutes, brightness and Eye Comfort use their configured schedule fallback; those HA controls have defaults and need no separate setup. A secret webhook or browser dashboard can provide lux without an HA sensor.

Time-based, Solar, and TV built-in sensor modes do not use the HA lux entity. In Ambient mode, the TV can also receive values from the secret webhook or browser dashboard.

## Address changes and discovery

The integration stores a stable TV device ID. If its saved address stops responding, it scans Home Assistant's local IPv4 subnets for the same ID, then updates the saved address. The scan covers subnets up to `/22` (1022 usable addresses); unusually large networks are narrowed to the `/24` containing Home Assistant. SSDP can also update the saved address when multicast reaches Home Assistant. A DHCP reservation is the most reliable setup. Discovery and subnet scans may not cross VLANs or isolated Wi-Fi networks.

If recovery still fails on a bridged VM, enable debug logging for `custom_components.panelcomfort.discovery` and check the `PanelComfort discovery will scan ...` message. It shows which subnet Home Assistant is actually scanning; a TV outside those ranges cannot be found by the fallback scan.

## Troubleshooting

- Verify the TV endpoint is enabled and the TV app shows **LAN API running**.
- Keep the TV port consistent (default `8765`). Guest Wi-Fi and wireless-client isolation can block access.
- If Movie Mode changes HyperHDR before the screen visibly changes, check **Screen Apply Result**. The app sends the Luna screen request before it adjusts HyperHDR, but webOS does not report measured panel output. `rejected`, `error`, or `no-luna-send` means the request failed; `sent` means only that the service accepted it. Check `/var/lib/webosbrew/panelcomfort/service.log` on the TV for the Luna response.
- If ambient mode does not respond, confirm the selected entity reports a numeric, available lux value and that **Brightness Calculation** is set to **Home Assistant lux sensor**. Adjust **Ambient Lux Minimum/Maximum** if your room's readings do not span the default 5–500 lx range.

## Security

The local Home Assistant endpoint has no per-client authentication. It accepts private IPv4 clients, which is a coarse network boundary rather than a same-subnet check. Use it only on a trusted home LAN and never port-forward it. The separate webhook feature uses an eight-character secret URL and has the same private-IPv4 restriction.
