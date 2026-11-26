from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PanelComfortConfigEntry
from .entity import PanelComfortEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: PanelComfortConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([PanelComfortEyeComfortActive(entry.runtime_data)])


class PanelComfortEyeComfortActive(PanelComfortEntity, BinarySensorEntity):
    """Whether PanelComfort currently targets Eye Comfort on."""

    _attr_name = "Eye Comfort Target"
    _attr_icon = "mdi:eye-check-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "eye_comfort_active")

    @property
    def is_on(self) -> bool:
        return self.status.get("eye_comfort") == "on"
