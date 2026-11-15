<img src="custom_components/panelcomfort/brand/icon.png" alt="" width="64" height="64" align="right">

# PanelComfort

Automatically dim a rooted LG webOS TV in the evening and brighten it during the day.

[![Add to Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=vibribbonee&repository=panelcomfort-webos&category=integration)

## Features

- Schedule panel brightness by time, sun elevation, or room light.
- Set a separate schedule for Eye Comfort and temporarily override brightness in Movie Mode.
- Adjust HyperHDR lighting alongside the TV and expose controls in Home Assistant.

![PanelComfort’s preview of the daily backlight curve and evening fade](docs/brightness-curve.jpg)

## Install

1. On the TV, open **Homebrew Channel → Settings → Add repository** and enter the [Homebrew catalog URL](https://raw.githubusercontent.com/vibribbonee/arcguard/main/repo.json). Install **PanelComfort**, or download the [IPK from Releases](https://github.com/vibribbonee/panelcomfort-webos/releases/latest).
2. Open PanelComfort and install or update its service when prompted. Choose a schedule and select **Save & apply**. Use **Repair / update service** after upgrading the IPK.
3. For Home Assistant control, enable **Home Assistant API** on the TV and install the integration with the button above. Restart Home Assistant and accept discovery, or add **PanelComfort** with the TV’s address and port `8765`. Keep the existing entry when upgrading.

Tested on LG UP78 (43UP78006LB), webOS 6.3.2-425.

## Use it

- Use **Ambient LEDs → Connection settings** to test HyperHDR and select your instances.
- Use **Movie Mode** for a temporary brightness override.

Keep TV controls on a trusted local network. The optional browser dashboard has no login.

[Settings and troubleshooting](docs/settings.md) · [Release notes](https://github.com/vibribbonee/panelcomfort-webos/releases/latest) · Build with `./build-ipk.sh` and test with `./tests/run-tests.sh`.

## Contributing

Pull requests are welcome. Describe the change and how you tested it.

[MIT license](LICENSE). OpenAI Codex assisted with development, testing, and documentation.
