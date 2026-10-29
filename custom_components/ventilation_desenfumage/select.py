"""Sélecteur : mode saisonnier automatique ou forcé."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentilationConfigEntry
from .entity import VentilationEntity
from .logic import SEASON_AUTO, SEASONS


async def async_setup_entry(
    hass: HomeAssistant, entry: VentilationConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SeasonSelect(entry.runtime_data)])


class SeasonSelect(VentilationEntity, SelectEntity):
    """Auto (selon la moyenne 24 h) ou mode imposé."""

    _attr_icon = "mdi:calendar-sync"
    _attr_options = [SEASON_AUTO, *SEASONS]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "choix_mode", "Choix du mode")

    @property
    def current_option(self) -> str:
        return self.coordinator.settings.season_force

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_update_setting("season_force", option)
