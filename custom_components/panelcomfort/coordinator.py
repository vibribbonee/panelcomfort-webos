"""One status poll per TV, shared by every PanelComfort entity."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_ID,
    CONF_ENTITY_KEY,
    CONF_HOST,
    CONF_PORT,
    CONTROL_PATH,
    DEFAULT_PORT,
    DOMAIN,
    REDISCOVERY_COOLDOWN_SECONDS,
    SCAN_INTERVAL_SECONDS,
)
from .discovery import async_find_device, legacy_identity

_LOGGER = logging.getLogger(__name__)
_REQUEST_ERRORS = (aiohttp.ClientError, TimeoutError, ValueError, HomeAssistantError)
# The TV keeps a lux sample fresh for three minutes; resend unchanged readings
# at least once a minute so it never falls back to the clock schedule.
_LUX_REFRESH_SECONDS = 60
CONF_AMBIENT_LUX_ENTITY = "ambient_lux_entity"

type PanelComfortConfigEntry = ConfigEntry[PanelComfortCoordinator]


def parse_lux(value: Any) -> int | None:
    """Return a plausible illuminance reading in whole lux, or None."""
    try:
        lux = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 <= lux <= 200000:
        return None
    return int(round(lux))


def _tv_lost_lux(payload: dict[str, Any] | None) -> bool:
    """True when the TV wants lux but fell back to its clock (e.g. just booted)."""
    data = payload or {}
    return data.get("fade_method") == "ambient" and data.get("phase") in (
        "day", "night", "morning-fade", "evening-fade"
    )


class PanelComfortCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the TV once per cycle, forward lux, and serialize setting changes."""

    config_entry: PanelComfortConfigEntry

    def __init__(self, hass: HomeAssistant, entry: PanelComfortConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        data = entry.data
        self.host: str = data[CONF_HOST]
        self.port = int(data.get(CONF_PORT, DEFAULT_PORT))
        self.device_id: str = (
            data.get(CONF_DEVICE_ID) or legacy_identity(entry.unique_id or self.host)
        )
        self.entity_key: str = data.get(CONF_ENTITY_KEY, self.device_id)
        self._write_lock = asyncio.Lock()
        self._last_rediscovery = 0.0
        self._lux_entity_id = ""
        self._lux_unsub = None
        self._last_lux: int | None = None
        self._last_lux_sent_at = 0.0

    # Device identity -----------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name="PanelComfort TV",
            manufacturer="PanelComfort",
            model="LG webOS panel scheduler",
            configuration_url=f"http://{self.host}:{self.port}{CONTROL_PATH}?action=status",
        )

    def _url(self, query: str) -> str:
        return f"http://{self.host}:{self.port}{CONTROL_PATH}?{query}"

    async def async_request(self, query: str) -> dict[str, Any]:
        """Send one API request and confirm the saved TV answered it."""
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=10.0, connect=2.0)
        async with session.get(
            self._url(query), timeout=timeout, headers={"Cache-Control": "no-cache"}
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise HomeAssistantError("PanelComfort returned an unsuccessful response")
        actual_id = str(payload.get("device_id", ""))
        if actual_id and self.device_id.startswith("legacy-"):
            # Adopt the TV's stable identity the first time a legacy entry sees it.
            self.device_id = actual_id
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_DEVICE_ID: actual_id},
                unique_id=actual_id,
            )
        elif actual_id and actual_id != self.device_id:
            raise HomeAssistantError("A different PanelComfort device answered at the saved address")
        return payload

    async def _async_rediscover(self, *, force: bool = False) -> bool:
        """Find the TV after a DHCP change; polling respects a cooldown."""
        now = time.monotonic()
        if not force and now - self._last_rediscovery < REDISCOVERY_COOLDOWN_SECONDS:
            return False
        self._last_rediscovery = now
        try:
            found = await async_find_device(self.hass, self.port, self.device_id, force=force)
        except Exception as err:  # noqa: BLE001 - discovery must never break polling
            _LOGGER.debug("PanelComfort rediscovery failed: %s", type(err).__name__)
            return False
        if not found:
            return False
        if found[CONF_HOST] != self.host:
            _LOGGER.info("PanelComfort TV found at a new address: %s", found[CONF_HOST])
        self.host = found[CONF_HOST]
        self.port = int(found[CONF_PORT])
        self.device_id = found[CONF_DEVICE_ID]
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_HOST: self.host,
                CONF_PORT: self.port,
                CONF_DEVICE_ID: self.device_id,
            },
        )
        return True

    async def _async_request_with_rediscovery(self, query: str, *, force: bool) -> dict[str, Any]:
        try:
            return await self.async_request(query)
        except _REQUEST_ERRORS:
            if not await self._async_rediscover(force=force):
                raise
            return await self.async_request(query)

    # Polling -------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            payload = await self._async_request_with_rediscovery("action=status", force=False)
        except _REQUEST_ERRORS as err:
            raise UpdateFailed(f"PanelComfort TV is not reachable: {type(err).__name__}") from err
        if await self._async_push_lux(payload):
            try:
                payload = await self.async_request("action=status")
            except _REQUEST_ERRORS as err:
                _LOGGER.debug("Status refresh after lux update failed: %s", type(err).__name__)
        return payload

    def _lux_stability(self, payload: dict[str, Any] | None) -> int:
        try:
            value = int((payload or {}).get("lux_stability", 10))
        except (TypeError, ValueError):
            return 10
        return value if 0 <= value <= 1000 else 10

    def _lux_wanted(self, payload: dict[str, Any]) -> bool:
        """Lux matters only for ambient brightness or Dynamic Eye Comfort."""
        return bool(self._lux_entity_id) and (
            payload.get("fade_method") == "ambient"
            or payload.get("eye_comfort_mode") in ("dynamic", "auto")
        )

    def _lux_due(self, lux: int, payload: dict[str, Any] | None) -> bool:
        return (
            self._last_lux is None
            or _tv_lost_lux(payload)
            or abs(lux - self._last_lux) > self._lux_stability(payload)
            or time.monotonic() - self._last_lux_sent_at >= _LUX_REFRESH_SECONDS
        )

    async def _async_push_lux(self, payload: dict[str, Any]) -> bool:
        """Forward the selected HA illuminance reading when the TV uses it."""
        if not self._lux_wanted(payload):
            return False
        state = self.hass.states.get(self._lux_entity_id)
        lux = parse_lux(state.state) if state is not None else None
        if lux is None or not self._lux_due(lux, payload):
            return False
        try:
            async with self._write_lock:
                response = await self.async_request(f"ambient_lux={lux}")
        except _REQUEST_ERRORS as err:
            _LOGGER.debug("PanelComfort lux update failed: %s", type(err).__name__)
            return False
        accepted = parse_lux(response.get("ambient_lux"))
        self._last_lux = lux if accepted is None else accepted
        self._last_lux_sent_at = time.monotonic()
        return True

    @callback
    def async_bind_lux_sensor(self) -> None:
        """Follow the selected lux sensor so new readings arrive promptly."""
        entity_id = self.config_entry.options.get(CONF_AMBIENT_LUX_ENTITY, "") or ""
        if entity_id == self._lux_entity_id:
            return
        if self._lux_unsub is not None:
            self._lux_unsub()
            self._lux_unsub = None
        self._lux_entity_id = entity_id
        self._last_lux = None
        self._last_lux_sent_at = 0.0
        if entity_id:
            self._lux_unsub = async_track_state_change_event(
                self.hass, [entity_id], self._handle_lux_change
            )

    @callback
    def _handle_lux_change(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        lux = parse_lux(new_state.state) if new_state is not None else None
        if lux is None or self.data is None or not self._lux_wanted(self.data):
            return
        if self._lux_due(lux, self.data):
            self.config_entry.async_create_task(self.hass, self.async_request_refresh())

    @callback
    def async_shutdown_lux(self) -> None:
        if self._lux_unsub is not None:
            self._lux_unsub()
            self._lux_unsub = None

    # Changes -------------------------------------------------------------

    async def async_apply(self, query: str) -> dict[str, Any]:
        """Save one setting on the TV and return the confirmed status."""
        async with self._write_lock:
            try:
                await self._async_request_with_rediscovery(query, force=True)
                payload = await self.async_request("action=status")
            except _REQUEST_ERRORS as err:
                raise HomeAssistantError(f"PanelComfort TV did not accept the change: {err}") from err
        # Publish the confirmed state to every entity right away.
        self.async_set_updated_data(payload)
        return payload
