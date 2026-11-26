from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PanelComfortConfigEntry
from .entity import PanelComfortEntity

SELECTS = (
    # key, name, labels to API values, icon, enabled by default
    ("fade_method", "Brightness Calculation", {
        "Time-based fade": "duration",
        "Solar elevation": "solar",
        "Home Assistant lux sensor": "ambient",
        "TV built-in sensor": "tv-sensor",
    }, "mdi:theme-light-dark", True),
    ("fade_curve", "Fade Curve", {
        "Linear": "linear", "Ease in": "easein", "Ease out": "easeout",
        "Smoothstep": "smooth", "Smootherstep": "smootherstep", "Twilight": "twilight",
        "Soft roll-off": "rolloff-soft", "Log roll-off": "rolloff",
        "Strong roll-off": "rolloff-strong", "Exponential": "exponential",
        "Late power curve": "gamma-late", "Early power curve": "gamma-early",
    }, "mdi:chart-bell-curve", False),
    ("dim_mode", "Evening Trigger", {"Fixed time": "fixed", "Sunset": "sunset"}, "mdi:weather-sunset-down", True),
    ("up_mode", "Morning Trigger", {"Fixed time": "fixed", "Sunrise": "sunrise"}, "mdi:weather-sunrise", True),
    ("eye_timing", "Eye Comfort Timing", {"Follow schedule": "linked", "Custom times": "custom"}, "mdi:eye-clock", True),
    ("eye_comfort_mode", "Eye Comfort Mode", {
        "Dynamic": "dynamic", "Time": "time", "On": "on", "Off": "off",
    }, "mdi:eye-check-outline", True),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PanelComfortConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(PanelComfortSelect(entry.runtime_data, *item) for item in SELECTS)


class PanelComfortSelect(PanelComfortEntity, SelectEntity):
    """A schedule choice saved on the TV."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key, name, choices, icon, enabled) -> None:
        super().__init__(coordinator, key)
        self.key = key
        self._values = choices
        self._labels = {value: label for label, value in choices.items()}
        self._attr_name = name
        self._attr_options = list(choices)
        self._attr_icon = icon
        self._attr_entity_registry_enabled_default = enabled

    @property
    def current_option(self) -> str | None:
        return self._labels.get(str(self.status.get(self.key, "")))

    async def async_select_option(self, option: str) -> None:
        value = self._values[option]
        payload = await self._async_apply(f"{self.key}={value}")
        if str(payload.get(self.key, "")) != value:
            raise HomeAssistantError(f"The TV did not confirm {self.name}")
