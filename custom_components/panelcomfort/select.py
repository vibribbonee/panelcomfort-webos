from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entity import PanelComfortConfigControl

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

SELECTS = (
    ("fade_method", "Brightness Calculation", "fade_method", {
        "Time-based fade": "duration",
        "Solar elevation": "solar",
        "Home Assistant lux sensor": "ambient",
        "TV built-in sensor": "tv-sensor",
    }, "mdi:theme-light-dark"),
    ("fade_curve", "Fade Curve", "fade_curve", {
        "Linear": "linear", "Ease in": "easein", "Ease out": "easeout",
        "Smoothstep": "smooth", "Smootherstep": "smootherstep", "Twilight": "twilight",
        "Soft roll-off": "rolloff-soft", "Log roll-off": "rolloff",
        "Strong roll-off": "rolloff-strong", "Exponential": "exponential",
        "Late power curve": "gamma-late", "Early power curve": "gamma-early",
    }, "mdi:chart-bell-curve"),
    ("dim_mode", "Evening Trigger", "dim_mode", {"Fixed time": "fixed", "Sunset": "sunset"}, "mdi:weather-sunset-down"),
    ("up_mode", "Morning Trigger", "up_mode", {"Fixed time": "fixed", "Sunrise": "sunrise"}, "mdi:weather-sunrise"),
    ("eye_timing", "Eye Comfort Timing", "eye_timing", {"Follow schedule": "linked", "Custom times": "custom"}, "mdi:eye-clock"),
    ("eye_comfort_mode", "Eye Comfort Mode", "eye_comfort_mode", {
        "Dynamic": "dynamic", "Time": "time", "On": "on", "Off": "off",
    }, "mdi:eye-check-outline"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([
        PanelComfortConfigSelect(hass, entry, key, name, status_key, choices, icon)
        for key, name, status_key, choices, icon in SELECTS
    ])


class PanelComfortConfigSelect(PanelComfortConfigControl, SelectEntity):
    """Editable HA select backed by the TV's persistent scheduler config."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = True

    def __init__(self, hass, entry, key, name, status_key, choices, icon):
        self._init_control(hass, entry, key)
        self.key = key
        self.status_key = status_key
        self.values = choices
        self._labels_by_value = {value: label for label, value in choices.items()}
        self._attr_name = name
        self._attr_options = list(choices)
        self._attr_icon = icon
        self._attr_current_option = None

    async def async_update(self) -> None:
        try:
            payload = await self._status()
            value = str(payload.get(self.status_key, ""))
            self._attr_current_option = self._labels_by_value.get(value)
        except Exception as err:
            self._available = False
            _LOGGER.debug("PanelComfort select update failed for %s: %s", self.key, type(err).__name__)

    async def async_select_option(self, option: str) -> None:
        value = self.values.get(option)
        if value is None:
            return
        try:
            payload = await self._apply(f"{self.key}={value}")
            actual = str(payload.get(self.status_key, ""))
            self._attr_current_option = self._labels_by_value.get(actual)
            if actual != value:
                raise ValueError(f"TV did not confirm {self._attr_name}")
            self._available = True
            self.async_write_ha_state()
        except Exception as err:
            self._available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not change PanelComfort {self._attr_name}: {err}") from err
