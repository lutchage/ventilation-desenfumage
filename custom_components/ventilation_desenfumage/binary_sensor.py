"""Capteurs binaires : états de sécurité et de fonctionnement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentilationConfigEntry
from .coordinator import VentilationCoordinator
from .entity import VentilationEntity


@dataclass(frozen=True)
class _Desc:
    key: str
    name: str
    device_class: BinarySensorDeviceClass | None
    icon: str | None
    value: Callable[[VentilationCoordinator], bool | None]


def _trace_active(c: VentilationCoordinator, key: str) -> bool | None:
    if c.data is None:
        return None
    return any(t.key == key and t.active for t in c.data.trace)


DESCRIPTIONS = [
    _Desc("alarme", "Alarme désenfumage", BinarySensorDeviceClass.SAFETY, "mdi:fire-alert",
          lambda c: _trace_active(c, "alarme")),
    _Desc("defaut_centrale", "Défaut", BinarySensorDeviceClass.PROBLEM, None,
          lambda c: _trace_active(c, "defaut")),
    _Desc("coupure_secteur", "Coupure secteur", BinarySensorDeviceClass.PROBLEM, "mdi:power-plug-off",
          lambda c: _trace_active(c, "coupure")),
    _Desc("maintenance", "Maintenance", None, "mdi:account-wrench",
          lambda c: _trace_active(c, "maintenance")),
    _Desc("station_meteo", "Panne station météo", BinarySensorDeviceClass.PROBLEM, "mdi:weather-cloudy-alert",
          lambda c: _trace_active(c, "station")),
    _Desc("meteo_defavorable", "Météo défavorable", None, "mdi:weather-pouring",
          lambda c: _trace_active(c, "meteo")),
    _Desc("commande_manuelle", "Commande manuelle active", None, "mdi:hand-back-right",
          lambda c: _trace_active(c, "manuel")),
    _Desc("demande_ventilation", "Demande de ventilation", None, "mdi:fan",
          lambda c: _trace_active(c, "ventilation")),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: VentilationConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(VentilationBinarySensor(entry.runtime_data, d) for d in DESCRIPTIONS)


class VentilationBinarySensor(VentilationEntity, BinarySensorEntity):
    """Capteur binaire dérivé de la trace de décision."""

    def __init__(self, coordinator: VentilationCoordinator, desc: _Desc) -> None:
        super().__init__(coordinator, desc.key, desc.name)
        self._desc = desc
        self._attr_device_class = desc.device_class
        if desc.icon:
            self._attr_icon = desc.icon

    @property
    def is_on(self) -> bool | None:
        return self._desc.value(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data
        if d is None:
            return {}
        item = next((t for t in d.trace if t.key == self._desc.key or t.key == _KEY_MAP.get(self._desc.key)), None)
        return {"raison": item.reason} if item and item.reason else {}


_KEY_MAP = {
    "defaut_centrale": "defaut",
    "coupure_secteur": "coupure",
    "station_meteo": "station",
    "meteo_defavorable": "meteo",
    "commande_manuelle": "manuel",
    "demande_ventilation": "ventilation",
}
