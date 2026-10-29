"""Boutons : OUVRIR, FERMER, retour en automatique."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentilationConfigEntry
from .entity import VentilationEntity
from .logic import TARGET_CLOSE, TARGET_OPEN


async def async_setup_entry(
    hass: HomeAssistant, entry: VentilationConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            ManualButton(c, "ouvrir", "Ouvrir", TARGET_OPEN, "mdi:window-open-variant"),
            ManualButton(c, "fermer", "Fermer", TARGET_CLOSE, "mdi:window-closed-variant"),
            ResumeButton(c),
            ResetCountersButton(c),
        ]
    )


class ManualButton(VentilationEntity, ButtonEntity):
    """Commande manuelle (devient prioritaire pendant la durée réglée)."""

    def __init__(self, coordinator, key: str, name: str, target: str, icon: str) -> None:
        super().__init__(coordinator, key, name)
        self._target = target
        self._attr_icon = icon

    async def async_press(self) -> None:
        await self.coordinator.async_manual(self._target, self._context)


class ResumeButton(VentilationEntity, ButtonEntity):
    """Annuler la commande manuelle."""

    _attr_icon = "mdi:autorenew"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "retour_auto", "Retour en automatique")

    async def async_press(self) -> None:
        await self.coordinator.async_resume_auto()


class ResetCountersButton(VentilationEntity, ButtonEntity):
    """Remise à zéro des compteurs (utilisateurs autorisés)."""

    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "remise_a_zero_compteurs", "Remise à zéro des compteurs")

    async def async_press(self) -> None:
        await self.coordinator.async_reset_counters(self._context)
