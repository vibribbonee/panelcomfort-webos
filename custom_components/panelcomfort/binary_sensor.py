from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.components.binary_sensor import BinarySensorEntity
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
    async_add_entities([PanelComfortEyeComfortActive(hass, entry)])


class PanelComfortEyeComfortActive(BinarySensorEntity):
    """Report whether PanelComfort currently targets Eye Comfort on."""

    _attr_has_entity_name = True
    _attr_name = "Eye Comfort Target"
    _attr_icon = "mdi:eye-check-outline"
    _attr_should_poll = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._host = entry.data[CONF_HOST]
        self._port = int(entry.data.get(CONF_PORT, 8765))
        self._device_id = entry.data.get(CONF_DEVICE_ID, entry.unique_id)
        entity_key = entry.data.get(CONF_ENTITY_KEY, self._device_id)
        self._attr_unique_id = f"{entity_key}_eye_comfort_active"
        self._attr_device_info = self._device_info()
        self._attr_is_on = False
        self._available = False

    def _device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": "PanelComfort TV",
            "manufacturer": "PanelComfort",
            "model": "LG webOS panel scheduler",
            "configuration_url": f"http://{self._host}:{self._port}{CONTROL_PATH}?action=status",
        }

    @property
    def available(self) -> bool:
        return self._available

    async def _request(self) -> dict:
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=4.0, connect=2.0)
        url = f"http://{self._host}:{self._port}{CONTROL_PATH}?action=status"
        async with session.get(url, timeout=timeout, headers={"Cache-Control": "no-cache"}) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise HomeAssistantError("PanelComfort returned an invalid status")
        actual_id = str(payload.get("device_id", ""))
        if actual_id and not self._device_id.startswith("legacy-") and actual_id != self._device_id:
            raise HomeAssistantError("A different PanelComfort device answered at the saved address")
        return payload

    async def _rediscover(self) -> bool:
        found = await async_find_device(self.hass, self._port, self._device_id)
        if not found:
            return False
        self._host = found[CONF_HOST]
        self._port = int(found[CONF_PORT])
        self._device_id = found[CONF_DEVICE_ID]
        self._attr_device_info = self._device_info()
        updated = {
            **self.entry.data,
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_DEVICE_ID: self._device_id,
        }
        self.hass.config_entries.async_update_entry(self.entry, data=updated)
        return True

    async def async_update(self) -> None:
        try:
            try:
                payload = await async_cached_status(
                    self.entry.entry_id, self._request
                )
            except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError):
                if not await self._rediscover():
                    raise
                payload = await async_cached_status(
                    self.entry.entry_id, self._request, force=True
                )
            self._attr_is_on = payload.get("eye_comfort") == "on"
            self._available = True
        except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as err:
            self._available = False
            _LOGGER.debug("PanelComfort Eye Comfort state update failed: %s", type(err).__name__)
