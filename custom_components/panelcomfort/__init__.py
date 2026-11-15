from __future__ import annotations

from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import (
    CONF_DEVICE_ID,
    CONF_ENTITY_KEY,
    CONF_HOST,
    CONF_LEGACY_TOKEN,
    CONF_PORT,
    CONF_STATUS_URL,
    DEFAULT_PORT,
    DOMAIN,
)
from .discovery import async_probe_host, legacy_identity

PLATFORMS = [Platform.SWITCH, Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.TIME, Platform.BINARY_SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old URL/token entries to PanelComfort's local tokenless API."""
    if entry.version > 3:
        return False
    if entry.version < 3:
        data = dict(entry.data)
        host = data.get(CONF_HOST)
        port = int(data.get(CONF_PORT, DEFAULT_PORT))
        legacy_token = str(data.get(CONF_LEGACY_TOKEN, ""))
        if not host and data.get(CONF_STATUS_URL):
            parsed = urlsplit(data[CONF_STATUS_URL])
            host = parsed.hostname
            port = parsed.port or DEFAULT_PORT
            if not legacy_token and "/cgi-bin/pc-" in parsed.path:
                legacy_token = parsed.path.split("/cgi-bin/pc-", 1)[1]
        if not host:
            return False
        device = await async_probe_host(hass, host, port)
        device_id = (device or {}).get(CONF_DEVICE_ID) or data.get(CONF_DEVICE_ID)
        if not device_id:
            device_id = legacy_identity(legacy_token or entry.unique_id or f"{host}:{port}")
        stable_host = (device or {}).get(CONF_HOST, host)
        stable_port = int((device or {}).get(CONF_PORT, port))
        entity_key = data.get(CONF_ENTITY_KEY) or entry.unique_id or device_id
        new_data = {
            CONF_HOST: stable_host,
            CONF_PORT: stable_port,
            CONF_DEVICE_ID: device_id,
            CONF_ENTITY_KEY: entity_key,
        }
        hass.config_entries.async_update_entry(entry, data=new_data, version=3, unique_id=device_id)
    return True
