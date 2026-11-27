from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PanelComfortConfigEntry
from .entity import PanelComfortEntity

SWITCHES = (
    # status key, name, icon, query parameter
    ("movie_override", "Movie Mode", "mdi:movie-open", "movie"),
    ("service_enabled", "Brightness Schedule", "mdi:calendar-clock", "service"),
    ("movie_brightness_enabled", "Custom Movie Brightness", "mdi:brightness-percent", "movie_brightness_custom"),
    ("eye_schedule_enabled", "Eye Comfort Schedule", "mdi:eye-check-outline", "eye_schedule"),
    ("eye_comfort", "Eye Comfort", "mdi:eye-check-outline", "eye_comfort_mode"),
    ("hyperhdr_enabled", "HyperHDR Control", "mdi:led-strip-variant", "hyperhdr"),
    ("hyperhdr_dark_curve", "LED Dark-Room Curve", "mdi:chart-bell-curve-cumulative", "hyperhdr_dark_curve"),
    ("profile_protection_enabled", "Picture Profile Protection", "mdi:television-shimmer", "profile_protection"),
)
_ATTRIBUTE_KEYS = ("phase", "backlight", "eye_comfort", "service_enabled", "hyperhdr_enabled", "hyperhdr_brightness")


async def async_setup_entry(
    hass: HomeAssistant, entry: PanelComfortConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(PanelComfortSwitch(entry.runtime_data, *item) for item in SWITCHES)


class PanelComfortSwitch(PanelComfortEntity, SwitchEntity):
    """Turn a PanelComfort feature on or off on the TV."""

    def __init__(self, coordinator, state_key, name, icon, parameter) -> None:
        super().__init__(coordinator, "movie_mode" if state_key == "movie_override" else state_key)
        self._state_key = state_key
        self._parameter = parameter
        self._attr_name = name
        self._attr_icon = icon

    @property
    def is_on(self) -> bool | None:
        if self._state_key not in self.status:
            return None
        value = self.status[self._state_key]
        # Eye Comfort reports "on"/"off"/"auto"; only an explicit on counts.
        return value == "on" if self._state_key == "eye_comfort" else bool(value)

    @property
    def extra_state_attributes(self) -> dict:
        return {key: self.status[key] for key in _ATTRIBUTE_KEYS if key in self.status}

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_apply(f"{self._parameter}=on")

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_apply(f"{self._parameter}=off")
