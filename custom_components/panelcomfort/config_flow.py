from __future__ import annotations

import ipaddress
from typing import Any

from homeassistant.core import callback

import voluptuous as vol
from homeassistant import config_entries

from .const import (
    CONF_DEVICE_ID,
    CONF_ENTITY_KEY,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
)
from .discovery import async_device_from_ssdp, async_discover_devices, async_probe_host


class PanelComfortConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Discover a PanelComfort TV without asking users to type URLs or tokens."""

    VERSION = 3

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PanelComfortOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Discover automatically, or pair directly by local IPv4 address."""
        if user_input is not None:
            host = str(user_input.get(CONF_HOST, "")).strip()
            try:
                port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
                if not 1 <= port <= 65535:
                    raise ValueError
            except (TypeError, ValueError):
                return self.async_show_form(
                    step_id="user", data_schema=self._user_schema(host), errors={"base": "invalid_port"}
                )
            if host:
                try:
                    address = ipaddress.ip_address(host)
                    if address.version != 4 or not address.is_private or address.is_loopback or address.is_link_local or address.is_multicast:
                        raise ValueError("not a private IPv4 address")
                except ValueError:
                    return self.async_show_form(
                        step_id="user", data_schema=self._user_schema(host), errors={"base": "invalid_host"}
                    )
                device = await async_probe_host(self.hass, host, port)
                if not device:
                    return self.async_show_form(
                        step_id="user", data_schema=self._user_schema(host, port), errors={"base": "cannot_connect"}
                    )
                self._pending_device = device
                await self.async_set_unique_id(device[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured(updates=self._entry_data(device))
                return await self.async_step_confirm()
            devices = await async_discover_devices(self.hass, port)
            if not devices:
                return self.async_show_form(
                    step_id="user", data_schema=self._user_schema(host, port), errors={"base": "cannot_find_device"}
                )
            if len(devices) == 1:
                self._pending_device = devices[0]
                await self.async_set_unique_id(devices[0][CONF_DEVICE_ID])
                self._abort_if_unique_id_configured(updates=self._entry_data(devices[0]))
                return await self.async_step_confirm()
            self._found = {d[CONF_DEVICE_ID]: d for d in devices}
            return await self.async_step_select_device()
        # Initial entry: try discovery before asking the user to type anything.
        devices = await async_discover_devices(self.hass, DEFAULT_PORT)
        if len(devices) == 1:
            self._pending_device = devices[0]
            await self.async_set_unique_id(devices[0][CONF_DEVICE_ID])
            self._abort_if_unique_id_configured(updates=self._entry_data(devices[0]))
            return await self.async_step_confirm()
        if len(devices) > 1:
            self._found = {d[CONF_DEVICE_ID]: d for d in devices}
            return await self.async_step_select_device()
        return self.async_show_form(step_id="user", data_schema=self._user_schema(), errors={})

    @staticmethod
    def _user_schema(host: str = "", port: int = DEFAULT_PORT):
        """Empty host retries discovery; a filled host performs direct pairing."""
        return vol.Schema({
            vol.Optional(CONF_HOST, default=host): str,
            vol.Optional(CONF_PORT, default=port): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        })

    async def async_step_ssdp(self, discovery_info):
        device = await async_device_from_ssdp(self.hass, discovery_info)
        if not device:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(device[CONF_DEVICE_ID])
        # When a configured TV re-announces from a new IP, update its config entry
        # rather than create a duplicate device or ask the user to pair again.
        self._abort_if_unique_id_configured(updates=self._entry_data(device))
        self._pending_device = device
        return await self.async_step_confirm()

    async def async_step_select_device(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            device = self._found.get(user_input["device"])
            if not device:
                return self.async_abort(reason="cannot_connect")
            self._pending_device = device
            await self.async_set_unique_id(device[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured(updates=self._entry_data(device))
            return await self.async_step_confirm()
        options = {device_id: f"PanelComfort TV ({device[CONF_HOST]})" for device_id, device in self._found.items()}
        return self.async_show_form(step_id="select_device", data_schema=vol.Schema({vol.Required("device"): vol.In(options)}))

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None):
        device = getattr(self, "_pending_device", None)
        if not device:
            return self.async_abort(reason="cannot_connect")
        if user_input is not None:
            return await self._async_create(device)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"host": device[CONF_HOST]},
        )

    @staticmethod
    def _entry_data(device: dict[str, Any]) -> dict[str, Any]:
        return {
            CONF_HOST: device[CONF_HOST],
            CONF_PORT: int(device[CONF_PORT]),
            CONF_DEVICE_ID: device[CONF_DEVICE_ID],
        }

    async def _async_create(self, device: dict[str, Any]):
        data = {**self._entry_data(device), CONF_ENTITY_KEY: device[CONF_DEVICE_ID]}
        await self.async_set_unique_id(data[CONF_DEVICE_ID])
        self._abort_if_unique_id_configured(updates=self._entry_data(device))
        return self.async_create_entry(title="PanelComfort TV", data=data)



class PanelComfortOptionsFlow(config_entries.OptionsFlow):
    """Choose an optional Home Assistant illuminance sensor to feed the TV."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data={"ambient_lux_entity": user_input.get("ambient_lux_entity", "")})
        choices = {"": "No ambient-light sensor"}
        for state in self.hass.states.async_all("sensor"):
            attrs = state.attributes
            unit = str(attrs.get("unit_of_measurement", "")).lower()
            if attrs.get("device_class") == "illuminance" and unit in ("lx", "lux"):
                choices[state.entity_id] = f"{attrs.get('friendly_name', state.entity_id)} ({state.entity_id})"
        current = self.config_entry.options.get("ambient_lux_entity", "")
        if current and current not in choices:
            choices[current] = f"Unavailable sensor ({current})"
        schema = vol.Schema({vol.Optional("ambient_lux_entity", default=current): vol.In(choices)})
        return self.async_show_form(step_id="init", data_schema=schema)
