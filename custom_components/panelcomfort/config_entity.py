from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_DEVICE_ID, CONF_ENTITY_KEY, CONF_HOST, CONF_PORT, CONTROL_PATH, DOMAIN
from .discovery import async_find_device
from .api import async_cached_status, async_config_lock, invalidate_status


class PanelComfortConfigControl:
    """Shared local API access for editable schedule entities."""

    def _init_control(self, hass: HomeAssistant, entry: ConfigEntry, suffix: str) -> None:
        self.hass = hass
        self.entry = entry
        self._host = entry.data[CONF_HOST]
        self._port = int(entry.data.get(CONF_PORT, 8765))
        self._device_id = entry.data.get(CONF_DEVICE_ID, entry.unique_id)
        entity_key = entry.data.get(CONF_ENTITY_KEY, self._device_id)
        self._attr_unique_id = f"{entity_key}_{suffix}"
        self._attr_device_info = self._device_info()
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

    def _url(self, query: str) -> str:
        return f"http://{self._host}:{self._port}{CONTROL_PATH}?{query}"

    async def _request(self, query: str) -> dict:
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=8.0, connect=2.0)
        async with session.get(self._url(query), timeout=timeout, headers={"Cache-Control": "no-cache"}) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise HomeAssistantError("PanelComfort returned an unsuccessful response")
        actual_id = str(payload.get("device_id", ""))
        if actual_id and not self._device_id.startswith("legacy-") and actual_id != self._device_id:
            raise HomeAssistantError("A different PanelComfort device answered at the saved address")
        return payload

    async def _rediscover(self, *, force: bool = False) -> bool:
        # Polling must respect the shared discovery cooldown: with the TV off, a forced
        # scan from every schedule entity meant a full subnet sweep each poll cycle.
        # Only explicit user changes (``_apply``) bypass it.
        found = await async_find_device(self.hass, self._port, self._device_id, force=force)
        if not found:
            return False
        was_legacy = self._device_id.startswith("legacy-")
        self._host = found[CONF_HOST]
        self._port = int(found[CONF_PORT])
        self._device_id = found[CONF_DEVICE_ID]
        self._attr_device_info = self._device_info()
        data = {
            **self.entry.data,
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_DEVICE_ID: self._device_id,
        }
        self.hass.config_entries.async_update_entry(
            self.entry, data=data, **({"unique_id": self._device_id} if was_legacy else {})
        )
        return True

    async def _status(self, *, force: bool = False) -> dict:
        try:
            payload = await async_cached_status(
                self.entry.entry_id,
                lambda: self._request("action=status"),
                force=force,
            )
        except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError):
            if not await self._rediscover():
                raise
            payload = await async_cached_status(
                self.entry.entry_id,
                lambda: self._request("action=status"),
                force=True,
            )
        self._available = True
        return payload

    async def _apply(self, query: str) -> dict:
        async with async_config_lock(self.entry.entry_id):
            try:
                await self._request(query)
            except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError):
                if not await self._rediscover(force=True):
                    raise
                await self._request(query)
            invalidate_status(self.entry.entry_id)
            return await self._status(force=True)
