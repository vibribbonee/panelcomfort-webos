from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PanelComfortConfigEntry
from .entity import PanelComfortEntity

TIMES = (
    ("dim_start", "Evening Start", "mdi:weather-sunset-down"),
    ("undim_start", "Morning Start", "mdi:weather-sunrise"),
    ("eye_start", "Eye Comfort Start", "mdi:eye-plus-outline"),
    ("eye_end", "Eye Comfort End", "mdi:eye-minus-outline"),
)


def _parse(value) -> time | None:
    try:
        hour, minute = str(value).split(":", 1)
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: PanelComfortConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(PanelComfortTime(entry.runtime_data, *item) for item in TIMES)


class PanelComfortTime(PanelComfortEntity, TimeEntity):
    """A clock time saved on the TV and applied immediately."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key, name, icon) -> None:
        super().__init__(coordinator, key)
        self.key = key
        self._attr_name = name
        self._attr_icon = icon

    @property
    def native_value(self) -> time | None:
        return _parse(self.status.get(self.key))

    async def async_set_value(self, value: time) -> None:
        payload = await self._async_apply(f"{self.key}={value.strftime('%H:%M')}")
        if _parse(payload.get(self.key)) != value.replace(second=0, microsecond=0):
            raise HomeAssistantError(f"The TV did not confirm {self.name}")
