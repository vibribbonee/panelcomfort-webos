from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import async_cached_status
from .const import CONF_DEVICE_ID, CONF_ENTITY_KEY, CONF_HOST, CONF_PORT, CONTROL_PATH, DOMAIN
from .discovery import async_find_device

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([
        PanelComfortSensor(hass, entry, "backlight", "Backlight Target", PERCENTAGE, "mdi:brightness-6"),
        PanelComfortSensor(hass, entry, "hyperhdr_brightness", "HyperHDR Target", PERCENTAGE, "mdi:led-strip"),
        PanelComfortSensor(hass, entry, "phase", "Schedule Phase", None, "mdi:theme-light-dark"),
        PanelComfortSensor(hass, entry, "ambient_lux", "Ambient Illuminance", "lx", "mdi:brightness-5", SensorDeviceClass.ILLUMINANCE),
        PanelComfortSensor(hass, entry, "screen_apply_status", "Screen Apply Result", None, "mdi:television-check"),
    ])


class PanelComfortSensor(SensorEntity):
    """Read-only PanelComfort values with DHCP rediscovery and shared-device identity."""

    _attr_has_entity_name = True
    _attr_should_poll = True

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, key: str,
        name: str, unit: str | None, icon: str, device_class: SensorDeviceClass | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.key = key
        self._host = entry.data[CONF_HOST]
        self._port = int(entry.data.get(CONF_PORT, 8765))
        self._device_id = entry.data.get(CONF_DEVICE_ID, entry.unique_id)
        self._attr_name = name
        self._attr_unique_id = f"{entry.data.get(CONF_ENTITY_KEY, self._device_id)}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        if device_class == SensorDeviceClass.ILLUMINANCE:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = icon
        self._attr_device_info = self._device_info()
        self._state = None
        self._available = False
        self._attributes: dict = {}

    def _device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": "PanelComfort TV",
            "manufacturer": "PanelComfort",
            "model": "LG webOS panel scheduler",
            "configuration_url": f"http://{self._host}:{self._port}{CONTROL_PATH}?action=status",
        }

    @property
    def native_value(self):
        return self._state

    @property
    def available(self) -> bool:
        return self._available

    @property
    def extra_state_attributes(self) -> dict:
        return self._attributes

    async def _request(self) -> dict:
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=4.0, connect=2.0)
        url = f"http://{self._host}:{self._port}{CONTROL_PATH}?action=status"
        async with session.get(url, timeout=timeout, headers={"Cache-Control": "no-cache"}) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise HomeAssistantError("PanelComfort returned an invalid status")
        actual_id = str(data.get("device_id", ""))
        if actual_id and not self._device_id.startswith("legacy-") and actual_id != self._device_id:
            raise HomeAssistantError("A different PanelComfort device answered at the saved address")
        return data

    async def _rediscover(self) -> bool:
        found = await async_find_device(self.hass, self._port, self._device_id)
        if not found:
            return False
        self._host = found[CONF_HOST]
        self._port = int(found[CONF_PORT])
        actual_id = found[CONF_DEVICE_ID]
        was_legacy = self._device_id.startswith("legacy-")
        self._device_id = actual_id
        self._attr_device_info = self._device_info()
        new_data = {
            **self.entry.data,
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_DEVICE_ID: actual_id,
        }
        self.hass.config_entries.async_update_entry(
            self.entry, data=new_data, **({"unique_id": actual_id} if was_legacy else {})
        )
        return True

    async def async_update(self) -> None:
        try:
            try:
                data = await async_cached_status(
                    self.entry.entry_id, self._request
                )
            except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError):
                if not await self._rediscover():
                    raise
                data = await async_cached_status(
                    self.entry.entry_id, self._request, force=True
                )
            self._state = data.get(self.key)
            self._attributes = {
                "phase": data.get("phase"),
                "eye_comfort": data.get("eye_comfort"),
                "movie_override": data.get("movie_override"),
                "brightness_offset": data.get("backlight_offset", 0),
                "ambient_lux": data.get("ambient_lux", 0),
                "fade_method": data.get("fade_method", "duration"),
                "service_enabled": data.get("service_enabled"),
                "screen_apply_backlight": data.get("screen_apply_backlight"),
                "screen_apply_updated": data.get("screen_apply_updated"),
            }
            self._available = self._state is not None
        except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as err:
            self._available = False
            _LOGGER.debug("PanelComfort sensor update failed: %s", type(err).__name__)
