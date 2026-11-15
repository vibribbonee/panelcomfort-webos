from __future__ import annotations

DOMAIN = "panelcomfort"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_DEVICE_ID = "device_id"
CONF_ENTITY_KEY = "entity_key"
# Legacy config keys used only to migrate the previous URL/token integration.
CONF_STATUS_URL = "status_url"
CONF_MOVIE_ON_URL = "movie_on_url"
CONF_MOVIE_OFF_URL = "movie_off_url"
CONF_LEGACY_TOKEN = "token"
DEFAULT_PORT = 8765
DISCOVERY_PATH = "/cgi-bin/panelcomfort-discovery.cgi"
CONTROL_PATH = "/cgi-bin/panelcomfort-ha.cgi"
SCAN_INTERVAL_SECONDS = 30
REDISCOVERY_COOLDOWN_SECONDS = 45
