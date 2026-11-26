from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import LIGHT_LUX, PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PanelComfortConfigEntry
from .entity import PanelComfortEntity

SENSORS = (
    # key, name, unit, icon, device class, diagnostic
    ("backlight", "Backlight Target", PERCENTAGE, "mdi:brightness-6", None, False),
    ("hyperhdr_brightness", "HyperHDR Target", PERCENTAGE, "mdi:led-strip", None, False),
    ("phase", "Schedule Phase", None, "mdi:theme-light-dark", None, False),
    ("ambient_lux", "Ambient Illuminance", LIGHT_LUX, "mdi:brightness-5", SensorDeviceClass.ILLUMINANCE, False),
    ("screen_apply_status", "Screen Apply Result", None, "mdi:television-check", None, True),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PanelComfortConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(PanelComfortSensor(entry.runtime_data, *item) for item in SENSORS)


class PanelComfortSensor(PanelComfortEntity, SensorEntity):
    """A read-only value from the TV's current schedule state."""

    def __init__(self, coordinator, key, name, unit, icon, device_class, diagnostic) -> None:
        super().__init__(coordinator, key)
        self.key = key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_class = device_class
        if device_class == SensorDeviceClass.ILLUMINANCE:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return super().available and self.status.get(self.key) is not None

    @property
    def native_value(self):
        return self.status.get(self.key)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.status
        return {
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
