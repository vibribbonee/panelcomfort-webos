# PanelComfort for Home Assistant

Control a rooted LG webOS TV’s brightness schedule, Eye Comfort, Movie Mode, and optional HyperHDR lighting from Home Assistant.

[![Add to Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=vibribbonee&repository=panelcomfort-webos&category=integration)

1. Install PanelComfort on the TV and open its **Home Assistant** tab. Enable the API and select **Save & apply**.
2. Install the integration from Marketplace and restart Home Assistant.
3. Accept discovery, or add **PanelComfort** in **Settings → Devices & services** with the TV’s address and port `8765`.

Select an illuminance sensor in the integration options if you want Home Assistant to supply room-light readings. Brightness and Eye Comfort use their configured schedules when readings are stale.

[Full setup](https://github.com/vibribbonee/panelcomfort-webos#install) · [Settings and troubleshooting](https://github.com/vibribbonee/panelcomfort-webos/blob/main/docs/settings.md)
