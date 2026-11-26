from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import DEGREE, LIGHT_LUX, PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PanelComfortConfigEntry
from .entity import PanelComfortEntity

S, B = NumberMode.SLIDER, NumberMode.BOX
# key, name, min, max, unit, icon, mode, step, enabled by default.
# Fine-tuning values start hidden on new installs; enable them on the device page.
NUMBERS = (
    ("backlight_offset", "Brightness Offset", -30, 30, PERCENTAGE, "mdi:brightness-percent", S, 1, True),
    ("min_brightness", "Night Minimum Backlight", 0, 70, PERCENTAGE, "mdi:brightness-4", S, 1, True),
    ("max_brightness", "Day Maximum Backlight", 1, 100, PERCENTAGE, "mdi:brightness-7", S, 1, True),
    ("movie_brightness", "Movie Mode Brightness", 0, 100, PERCENTAGE, "mdi:movie-open", S, 1, True),
    ("eye_lux_threshold", "Eye Comfort Lux Threshold", 0, 200000, LIGHT_LUX, "mdi:eye-outline", B, 1, True),
    ("hyperhdr_min_brightness", "HyperHDR Night Minimum", 0, 100, PERCENTAGE, "mdi:led-strip-variant", S, 1, True),
    # The TV requires the day maximum to be at least 1%.
    ("hyperhdr_max_brightness", "HyperHDR Day Maximum", 1, 100, PERCENTAGE, "mdi:led-strip-variant", S, 1, True),
    ("ambient_lux_min", "Ambient Lux Minimum", 0, 199999, LIGHT_LUX, "mdi:brightness-4", B, 1, False),
    ("ambient_lux_max", "Ambient Lux Maximum", 1, 200000, LIGHT_LUX, "mdi:brightness-7", B, 1, False),
    ("lux_stability", "Lux Stability", 0, 1000, LIGHT_LUX, "mdi:blur-linear", B, 1, False),
    ("ambient_brightness_offset", "Ambient Brightness Offset", -30, 30, PERCENTAGE, "mdi:brightness-percent", S, 1, False),
    ("dim_duration", "Evening Fade Duration", 0, 720, UnitOfTime.MINUTES, "mdi:timer-sand", S, 1, True),
    ("undim_duration", "Morning Fade Duration", 0, 720, UnitOfTime.MINUTES, "mdi:timer-sand-complete", S, 1, True),
    ("sunset_offset", "Sunset Offset", -180, 180, UnitOfTime.MINUTES, "mdi:weather-sunset-down", S, 1, False),
    ("sunrise_offset", "Sunrise Offset", -180, 180, UnitOfTime.MINUTES, "mdi:weather-sunrise", S, 1, False),
    ("eye_start_offset", "Eye Comfort Start Offset", -720, 720, UnitOfTime.MINUTES, "mdi:eye-plus-outline", S, 1, False),
    ("eye_end_offset", "Eye Comfort End Offset", -720, 720, UnitOfTime.MINUTES, "mdi:eye-minus-outline", S, 1, False),
    ("sunset_lat", "Solar Latitude", -89, 89, DEGREE, "mdi:latitude", S, 0.0001, False),
    ("sunset_lon", "Solar Longitude", -180, 180, DEGREE, "mdi:longitude", S, 0.0001, False),
)
# The status reports the offset as "backlight_offset"; the API sets "brightness_offset".
_QUERY_KEYS = {"backlight_offset": "brightness_offset"}


async def async_setup_entry(
    hass: HomeAssistant, entry: PanelComfortConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(PanelComfortNumber(entry.runtime_data, *item) for item in NUMBERS)


class PanelComfortNumber(PanelComfortEntity, NumberEntity):
    """A numeric schedule setting saved on the TV."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key, name, minimum, maximum, unit, icon, mode, step, enabled) -> None:
        super().__init__(coordinator, "brightness_offset" if key == "backlight_offset" else key)
        self.key = key
        self._query_key = _QUERY_KEYS.get(key, key)
        self._attr_name = name
        self._min = minimum
        self._max = maximum
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = mode
        self._attr_native_step = step
        self._attr_entity_registry_enabled_default = enabled

    @property
    def native_min_value(self) -> float:
        # Keep the ambient range valid: minimum stays below the current maximum.
        if self.key == "ambient_lux_max":
            return max(1, min(200000, self._int("ambient_lux_min", 5) + 1))
        return self._min

    @property
    def native_max_value(self) -> float:
        if self.key == "ambient_lux_min":
            return max(0, min(199999, self._int("ambient_lux_max", 500) - 1))
        return self._max

    def _int(self, key: str, default: int) -> int:
        try:
            return int(self.status.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    def _bounded(self, value: float) -> float:
        value = round(float(value), 4) if self.native_step < 1 else int(round(float(value)))
        return max(self.native_min_value, min(self.native_max_value, value))

    @property
    def native_value(self) -> float | None:
        raw = self.status.get(self.key)
        if raw in (None, ""):
            return None
        try:
            return self._bounded(raw)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        bounded = self._bounded(value)
        requested = (
            f"{bounded:.4f}".rstrip("0").rstrip(".") if self.native_step < 1 else str(int(bounded))
        )
        await self._async_apply(f"{self._query_key}={requested}")
