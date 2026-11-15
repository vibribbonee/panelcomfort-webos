from __future__ import annotations

import logging
from datetime import time, timedelta

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entity import PanelComfortConfigControl

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
TIMES = (
    ("dim_start", "Evening Start", "dim_start", "mdi:weather-sunset-down"),
    ("undim_start", "Morning Start", "undim_start", "mdi:weather-sunrise"),
    ("eye_start", "Eye Comfort Start", "eye_start", "mdi:eye-plus-outline"),
    ("eye_end", "Eye Comfort End", "eye_end", "mdi:eye-minus-outline"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([PanelComfortTime(hass, entry, *item) for item in TIMES])


class PanelComfortTime(PanelComfortConfigControl, TimeEntity):
    """Editable clock time saved on the TV and applied immediately."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, key: str, name: str, status_key: str, icon: str):
        self._init_control(hass, entry, key)
        self.key = key
        self.status_key = status_key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_value: time | None = None

    async def async_update(self) -> None:
        try:
            payload = await self._status()
            raw = str(payload.get(self.status_key, ""))
            hour, minute = raw.split(":", 1)
            self._attr_native_value = time(int(hour), int(minute))
        except Exception as err:
            self._available = False
            _LOGGER.debug("PanelComfort time update failed for %s: %s", self.key, type(err).__name__)

    async def async_set_value(self, value: time) -> None:
        requested = value.strftime("%H:%M")
        try:
            payload = await self._apply(f"{self.key}={requested}")
            raw = str(payload.get(self.status_key, ""))
            hour, minute = raw.split(":", 1)
            actual = time(int(hour), int(minute))
            if actual != value:
                raise ValueError(f"TV did not confirm {self._attr_name}")
            self._attr_native_value = actual
            self._available = True
            self.async_write_ha_state()
        except Exception as err:
            self._available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not change PanelComfort {self._attr_name}: {err}") from err
