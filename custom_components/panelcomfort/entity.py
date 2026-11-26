"""Base entity for values read from the shared PanelComfort status."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PanelComfortCoordinator


class PanelComfortEntity(CoordinatorEntity[PanelComfortCoordinator]):
    """An entity on the PanelComfort TV device, keyed by its stable unique ID."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PanelComfortCoordinator, suffix: str) -> None:
        super().__init__(coordinator)
        # Unique IDs match earlier releases, so entity IDs and history are kept.
        self._attr_unique_id = f"{coordinator.entity_key}_{suffix}"

    @property
    def device_info(self):
        # Read live: the configuration URL follows the TV after a DHCP change.
        return self.coordinator.device_info

    @property
    def status(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    async def _async_apply(self, query: str) -> dict[str, Any]:
        try:
            return await self.coordinator.async_apply(query)
        except HomeAssistantError as err:
            raise HomeAssistantError(f"Could not change PanelComfort {self.name}: {err}") from err
