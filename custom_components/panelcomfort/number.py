from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, CONF_ENTITY_KEY, CONF_HOST, CONF_PORT, CONTROL_PATH, DOMAIN
from .discovery import async_find_device
from .api import async_cached_status, async_config_lock, invalidate_status

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([
        PanelComfortNumber(hass, entry, "backlight_offset", "Brightness Offset", -30, 30, "brightness_offset", "%", "mdi:brightness-percent"),
        PanelComfortNumber(hass, entry, "min_brightness", "Night Minimum Backlight", 0, 70, "min_brightness", "%", "mdi:brightness-4"),
        PanelComfortNumber(hass, entry, "max_brightness", "Day Maximum Backlight", 1, 100, "max_brightness", "%", "mdi:brightness-7"),
        PanelComfortNumber(hass, entry, "movie_brightness", "Movie Mode Brightness", 0, 100, "movie_brightness", "%", "mdi:movie-open"),
        PanelComfortNumber(hass, entry, "eye_lux_threshold", "Eye Comfort Lux Threshold", 0, 200000, "eye_lux_threshold", "lx", "mdi:eye-outline", mode="box"),
        PanelComfortNumber(hass, entry, "hyperhdr_min_brightness", "HyperHDR Night Minimum", 0, 100, "hyperhdr_min_brightness", "%", "mdi:led-strip-variant"),
        # The TV API requires the day maximum to be at least 1%; keep the HA
        # entity range aligned so a slider cannot submit a value the TV rejects.
        PanelComfortNumber(hass, entry, "hyperhdr_max_brightness", "HyperHDR Day Maximum", 1, 100, "hyperhdr_max_brightness", "%", "mdi:led-strip-variant"),
        PanelComfortNumber(hass, entry, "ambient_lux_min", "Ambient Lux Minimum", 0, 199999, "ambient_lux_min", "lx", "mdi:brightness-4", mode="box"),
        PanelComfortNumber(hass, entry, "ambient_lux_max", "Ambient Lux Maximum", 1, 200000, "ambient_lux_max", "lx", "mdi:brightness-7", mode="box"),
        PanelComfortNumber(hass, entry, "lux_stability", "Lux Stability", 0, 1000, "lux_stability", "lx", "mdi:blur-linear", mode="box"),
        PanelComfortNumber(hass, entry, "ambient_brightness_offset", "Ambient Brightness Offset", -30, 30, "ambient_brightness_offset", "%", "mdi:brightness-percent"),
        PanelComfortNumber(hass, entry, "dim_duration", "Evening Fade Duration", 0, 720, "dim_duration", "min", "mdi:timer-sand"),
        PanelComfortNumber(hass, entry, "undim_duration", "Morning Fade Duration", 0, 720, "undim_duration", "min", "mdi:timer-sand-complete"),
        PanelComfortNumber(hass, entry, "sunset_offset", "Sunset Offset", -180, 180, "sunset_offset", "min", "mdi:weather-sunset-down"),
        PanelComfortNumber(hass, entry, "sunrise_offset", "Sunrise Offset", -180, 180, "sunrise_offset", "min", "mdi:weather-sunrise"),
        PanelComfortNumber(hass, entry, "eye_start_offset", "Eye Comfort Start Offset", -720, 720, "eye_start_offset", "min", "mdi:eye-plus-outline"),
        PanelComfortNumber(hass, entry, "eye_end_offset", "Eye Comfort End Offset", -720, 720, "eye_end_offset", "min", "mdi:eye-minus-outline"),
        PanelComfortNumber(hass, entry, "sunset_lat", "Solar Latitude", -89, 89, "sunset_lat", "°", "mdi:latitude", step=0.0001),
        PanelComfortNumber(hass, entry, "sunset_lon", "Solar Longitude", -180, 180, "sunset_lon", "°", "mdi:longitude", step=0.0001),
    ])


class PanelComfortNumber(NumberEntity):
    """Set an allow-listed PanelComfort configuration value."""

    _attr_has_entity_name = True
    _attr_native_step = 1
    _attr_mode = "slider"
    _attr_should_poll = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        key: str,
        name: str,
        minimum: int | float,
        maximum: int | float,
        query_key: str,
        unit: str,
        icon: str,
        step: float = 1,
        mode: str = "slider",
    ):
        self.hass = hass
        self.entry = entry
        self.key = key
        self.query_key = query_key
        self._host = entry.data[CONF_HOST]
        self._port = int(entry.data.get(CONF_PORT, 8765))
        self._device_id = entry.data.get(CONF_DEVICE_ID, entry.unique_id)
        entity_key = entry.data.get(CONF_ENTITY_KEY, self._device_id)
        self._attr_name = name
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_mode = mode
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        entity_suffix = "brightness_offset" if key == "backlight_offset" else key
        self._attr_unique_id = f"{entity_key}_{entity_suffix}"
        self._attr_device_info = self._device_info()
        self._attr_native_value = None if key in ("sunset_lat", "sunset_lon") else 0
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
        timeout = aiohttp.ClientTimeout(total=10.0, connect=2.0)
        async with session.get(self._url(query), timeout=timeout, headers={"Cache-Control": "no-cache"}) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise HomeAssistantError("PanelComfort rejected the request")
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
                    self.entry.entry_id, lambda: self._request("action=status")
                )
            except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError):
                if not await self._rediscover():
                    raise
                data = await async_cached_status(
                    self.entry.entry_id, lambda: self._request("action=status"), force=True
                )
            if self.key == "ambient_lux_min":
                current_max = int(data.get("ambient_lux_max", 500) or 500)
                self._attr_native_max_value = max(0, min(199999, current_max - 1))
            elif self.key == "ambient_lux_max":
                current_min = int(data.get("ambient_lux_min", 5) or 0)
                self._attr_native_min_value = max(1, min(200000, current_min + 1))
            raw = data.get(self.key)
            self._attr_native_value = (
                None if raw in (None, "") else max(
                    self._attr_native_min_value,
                    min(self._attr_native_max_value, round(float(raw), 4) if self._attr_native_step < 1 else int(raw)),
                )
            )
            self._available = True
        except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as err:
            self._available = False
            _LOGGER.debug("PanelComfort number update failed for %s: %s", self.key, type(err).__name__)

    async def async_set_native_value(self, value: float) -> None:
        bounded = max(
            self._attr_native_min_value,
            min(self._attr_native_max_value, round(float(value), 4) if self._attr_native_step < 1 else int(round(value))),
        )
        requested = f"{bounded:.4f}".rstrip("0").rstrip(".") if self._attr_native_step < 1 else str(bounded)
        try:
            async with async_config_lock(self.entry.entry_id):
                try:
                    await self._request(f"{self.query_key}={requested}")
                except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError):
                    if not await self._rediscover():
                        raise
                    await self._request(f"{self.query_key}={requested}")
                invalidate_status(self.entry.entry_id)
                await self.async_update()
                if not self._available:
                    raise HomeAssistantError(f"PanelComfort could not confirm {self._attr_name}")
                # If another client made a newer change, show the saved value
                # rather than marking this entity unavailable.
                self.async_write_ha_state()
        except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as err:
            self._available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not update PanelComfort {self._attr_name}: {err}") from err
