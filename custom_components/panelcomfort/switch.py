from __future__ import annotations

import logging
import time
from datetime import timedelta

import aiohttp
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_ID,
    CONF_ENTITY_KEY,
    CONF_HOST,
    CONF_PORT,
    CONTROL_PATH,
    DOMAIN,
    REDISCOVERY_COOLDOWN_SECONDS,
    SCAN_INTERVAL_SECONDS,
)
from .discovery import async_find_device, async_probe_host, legacy_identity
from .api import async_cached_status, async_config_lock, invalidate_status

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([
        PanelComfortMovieSwitch(hass, entry),
        PanelComfortMovieSwitch(
            hass, entry,
            state_key="service_enabled",
            name="Brightness Schedule",
            icon="mdi:calendar-clock",
            on_query="service=on",
            off_query="service=off",
            push_lux=False,
        ),
        PanelComfortMovieSwitch(
            hass, entry,
            state_key="movie_brightness_enabled",
            name="Custom Movie Brightness",
            icon="mdi:brightness-percent",
            on_query="movie_brightness_custom=on",
            off_query="movie_brightness_custom=off",
            push_lux=False,
        ),
        PanelComfortMovieSwitch(
            hass, entry,
            state_key="eye_schedule_enabled",
            name="Eye Comfort Schedule",
            icon="mdi:eye-check-outline",
            on_query="eye_schedule=on",
            off_query="eye_schedule=off",
            push_lux=False,
        ),
        PanelComfortMovieSwitch(
            hass, entry,
            state_key="eye_comfort",
            name="Eye Comfort",
            icon="mdi:eye-check-outline",
            on_query="eye_comfort_mode=on",
            off_query="eye_comfort_mode=off",
            push_lux=False,
        ),
        PanelComfortMovieSwitch(
            hass, entry,
            state_key="hyperhdr_enabled",
            name="HyperHDR Control",
            icon="mdi:led-strip-variant",
            on_query="hyperhdr=on",
            off_query="hyperhdr=off",
            push_lux=False,
        ),
        PanelComfortMovieSwitch(
            hass, entry,
            state_key="profile_protection_enabled",
            name="Picture Profile Protection",
            icon="mdi:television-shimmer",
            on_query="profile_protection=on",
            off_query="profile_protection=off",
            push_lux=False,
        ),
    ])


class PanelComfortMovieSwitch(SwitchEntity):
    """Native Home Assistant switch for PanelComfort Movie override."""

    _attr_has_entity_name = True
    _attr_name = "Movie Mode"
    _attr_icon = "mdi:movie-open"
    _attr_should_poll = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        state_key: str = "movie_override",
        name: str = "Movie Mode",
        icon: str = "mdi:movie-open",
        on_query: str = "movie=on",
        off_query: str = "movie=off",
        push_lux: bool = True,
    ) -> None:
        self.hass = hass
        self.entry = entry
        data = entry.data
        self._host = data[CONF_HOST]
        self._port = int(data.get(CONF_PORT, 8765))
        self._device_id = data.get(CONF_DEVICE_ID) or legacy_identity(entry.unique_id or self._host)
        self._entity_key = data.get(CONF_ENTITY_KEY, self._device_id)
        self._state_key = state_key
        self._on_query = on_query
        self._off_query = off_query
        self._push_lux_enabled = push_lux
        self._attr_name = name
        self._attr_icon = icon
        entity_suffix = "movie_mode" if state_key == "movie_override" else state_key
        self._attr_unique_id = f"{self._entity_key}_{entity_suffix}"
        self._attr_device_info = self._device_info()
        self._is_on: bool | None = None
        self._available = False
        self._attributes: dict = {}
        self._last_rediscovery = 0.0
        self._last_lux_value: int | None = None
        self._last_lux_pushed_at = 0.0
        self._lux_stability = 10
        self._lux_entity_id = ""
        self._lux_state_unsub = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._push_lux_enabled:
            return
        self.async_on_remove(self.entry.add_update_listener(self._async_entry_updated))
        self._bind_lux_sensor()

    async def _async_entry_updated(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        if self._bind_lux_sensor():
            invalidate_status(self.entry.entry_id)
            self.async_schedule_update_ha_state(force_refresh=True)

    def _bind_lux_sensor(self) -> bool:
        """Track the selected HA sensor so new readings are forwarded promptly."""
        entity_id = self.entry.options.get("ambient_lux_entity", "") if self._push_lux_enabled else ""
        if entity_id == self._lux_entity_id:
            return False
        if self._lux_state_unsub is not None:
            self._lux_state_unsub()
            self._lux_state_unsub = None
        self._lux_entity_id = entity_id
        self._last_lux_value = None
        self._last_lux_pushed_at = 0.0
        if entity_id:
            self._lux_state_unsub = async_track_state_change_event(
                self.hass, [entity_id], self._handle_lux_state_change
            )
        return True

    @callback
    def _handle_lux_state_change(self, event) -> None:
        """Schedule an immediate refresh when the selected lux reading changes."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None or (old_state is not None and old_state.state == new_state.state):
            return
        lux = self._parse_lux(new_state.state)
        if lux is None:
            return
        if (
            self._last_lux_value is not None
            and abs(lux - self._last_lux_value) <= self._lux_stability
            and time.monotonic() - self._last_lux_pushed_at < 60
        ):
            return
        invalidate_status(self.entry.entry_id)
        self.async_schedule_update_ha_state(force_refresh=True)

    @staticmethod
    def _parse_lux(value: str) -> int | None:
        try:
            lux_float = float(value)
            if not 0 <= lux_float <= 200000:
                return None
            return int(round(lux_float))
        except (TypeError, ValueError):
            return None

    def _device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": "PanelComfort TV",
            "manufacturer": "PanelComfort",
            "model": "LG webOS panel scheduler",
            "configuration_url": f"http://{self._host}:{self._port}{CONTROL_PATH}?action=status",
        }

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def available(self) -> bool:
        return self._available

    @property
    def extra_state_attributes(self) -> dict:
        return self._attributes

    def _url(self, query: str) -> str:
        return f"http://{self._host}:{self._port}{CONTROL_PATH}?{query}"

    async def _request(self, query: str) -> dict:
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=10.0, connect=2.0)
        async with session.get(self._url(query), timeout=timeout, headers={"Cache-Control": "no-cache"}) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise HomeAssistantError("PanelComfort returned an unsuccessful response")
        actual_id = str(payload.get("device_id", ""))
        if actual_id and not self._device_id.startswith("legacy-") and actual_id != self._device_id:
            raise HomeAssistantError("A different PanelComfort device answered at the saved address")
        if actual_id and self._device_id.startswith("legacy-"):
            self._device_id = actual_id
            self._attr_device_info = self._device_info()
            new_data = {**self.entry.data, CONF_DEVICE_ID: actual_id}
            self.hass.config_entries.async_update_entry(self.entry, data=new_data, unique_id=actual_id)
        return payload

    async def _rediscover(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self._last_rediscovery < REDISCOVERY_COOLDOWN_SECONDS:
            return False
        self._last_rediscovery = now
        try:
            found = await async_find_device(self.hass, self._port, self._device_id, force=force)
        except Exception as err:  # network discovery must not stop HA's polling loop
            _LOGGER.debug("PanelComfort rediscovery failed: %s", type(err).__name__)
            return False
        if not found:
            return False
        old_host = self._host
        self._host = found[CONF_HOST]
        self._port = int(found[CONF_PORT])
        self._device_id = found[CONF_DEVICE_ID]
        self._attr_device_info = self._device_info()
        updated = {**self.entry.data, CONF_HOST: self._host, CONF_PORT: self._port, CONF_DEVICE_ID: self._device_id}
        self.hass.config_entries.async_update_entry(self.entry, data=updated)
        if old_host != self._host:
            _LOGGER.info("PanelComfort rediscovered at %s (old address no longer used)", self._host)
        return True

    async def _push_ambient_lux(self) -> bool:
        """Forward the selected HA illuminance sensor value to PanelComfort."""
        if not self._push_lux_enabled:
            return False
        entity_id = self.entry.options.get("ambient_lux_entity", "")
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return False
        lux = self._parse_lux(state.state)
        if lux is None:
            return False
        # Keep the TV's three-minute freshness window alive even if lux is unchanged.
        if (
            self._last_lux_value is not None
            and abs(lux - self._last_lux_value) <= self._lux_stability
            and time.monotonic() - self._last_lux_pushed_at < 60
        ):
            return False
        try:
            async with async_config_lock(self.entry.entry_id):
                response = await self._request(f"ambient_lux={lux}")
                invalidate_status(self.entry.entry_id)
            accepted_lux = self._parse_lux(str(response.get("ambient_lux"))) if response.get("ambient_lux") is not None else None
            self._last_lux_value = lux if accepted_lux is None else accepted_lux
            self._last_lux_pushed_at = time.monotonic()
            return True
        except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as err:
            _LOGGER.debug("PanelComfort ambient lux push failed: %s", type(err).__name__)
            return False

    async def async_update(self, *, push_lux: bool = True) -> None:
        try:
            payload = await async_cached_status(
                self.entry.entry_id, lambda: self._request("action=status")
            )
        except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as err:
            if await self._rediscover(force=False):
                try:
                    payload = await async_cached_status(
                        self.entry.entry_id, lambda: self._request("action=status"), force=True
                    )
                except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as retry_err:
                    self._available = False
                    _LOGGER.debug("PanelComfort status failed after rediscovery: %s", type(retry_err).__name__)
                    return
            else:
                self._available = False
                _LOGGER.debug("PanelComfort status unavailable: %s", type(err).__name__)
                return
        # A Home Assistant illuminance entity is optional and is sent only when
        # this device is actually using the HA ambient-sensor calculation mode.
        try:
            stability = int(payload.get("lux_stability", 10))
            self._lux_stability = stability if 0 <= stability <= 1000 else 10
        except (TypeError, ValueError):
            self._lux_stability = 10
        if push_lux and (
            payload.get("fade_method") == "ambient"
            or payload.get("eye_comfort_mode") in ("dynamic", "auto")
        ):
            if await self._push_ambient_lux():
                try:
                    payload = await async_cached_status(
                        self.entry.entry_id, lambda: self._request("action=status"), force=True
                    )
                except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as err:
                    _LOGGER.debug("PanelComfort status refresh after lux update failed: %s", type(err).__name__)
        raw_state = payload.get(self._state_key, False)
        self._is_on = raw_state == "on" if self._state_key == "eye_comfort" else bool(raw_state)
        self._attributes = {
            key: payload[key]
            for key in ("phase", "backlight", "eye_comfort", "service_enabled", "hyperhdr_enabled", "hyperhdr_brightness")
            if key in payload
        }
        self._available = True

    async def _set_mode(self, query: str, desired_state: bool) -> None:
        try:
            async with async_config_lock(self.entry.entry_id):
                try:
                    await self._request(query)
                except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError):
                    if not await self._rediscover(force=True):
                        raise
                    await self._request(query)
                invalidate_status(self.entry.entry_id)
                # Do not push another lux sample during this confirmation.
                await self.async_update(push_lux=False)
                if not self._available:
                    raise HomeAssistantError(f"PanelComfort could not confirm {self._attr_name}")
                # A concurrent change from the browser may win; report its
                # saved state instead of treating that as an outage.
                self.async_write_ha_state()
        except (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError) as err:
            self._available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not change PanelComfort {self._attr_name}: {err}") from err

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_mode(self._on_query, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_mode(self._off_query, False)
