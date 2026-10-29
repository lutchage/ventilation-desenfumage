"""Entité de base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VentilationCoordinator


class VentilationEntity(CoordinatorEntity[VentilationCoordinator]):
    """Base commune : rattachement à l'appareil et identifiant unique."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VentilationCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Intégration personnalisée",
            model="Ouvrant de désenfumage (CPS-B1 + Shelly)",
        )
