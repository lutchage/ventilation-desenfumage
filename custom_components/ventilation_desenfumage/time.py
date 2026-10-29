"""Réglages horaires : aération quotidienne et plage interdite."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentilationConfigEntry
from .entity import VentilationEntity
from .logic import parse_time


async def async_setup_entry(
    hass: HomeAssistant, entry: VentilationConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            SettingTime(c, "heure_aeration", "Heure de l'aération quotidienne", "aeration_time", "mdi:clock-outline"),
            SettingTime(c, "plage_interdite_debut", "Début de la plage interdite", "quiet_start", "mdi:clock-start"),
            SettingTime(c, "plage_interdite_fin", "Fin de la plage interdite", "quiet_end", "mdi:clock-end"),
        ]
    )


class SettingTime(VentilationEntity, TimeEntity):
    """Heure réglable."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str, name: str, setting: str, icon: str) -> None:
        super().__init__(coordinator, key, name)
        self._setting = setting
        self._attr_icon = icon

    @property
    def native_value(self) -> time:
        return parse_time(getattr(self.coordinator.settings, self._setting))

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_update_setting(self._setting, value.strftime("%H:%M:%S"))
