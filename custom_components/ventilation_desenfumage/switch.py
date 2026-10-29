"""Interrupteurs : mode ventilation, système armé, plage interdite."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentilationConfigEntry
from .entity import VentilationEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: VentilationConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            SettingSwitch(c, "ventilation", "Mode ventilation", "ventilation_enabled", "mdi:fan"),
            SettingSwitch(c, "plage_interdite", "Plage horaire interdite", "quiet_enabled", "mdi:sleep"),
            ArmedSwitch(c),
        ]
    )


class SettingSwitch(VentilationEntity, SwitchEntity):
    """Interrupteur lié à un réglage booléen."""

    def __init__(self, coordinator, key: str, name: str, setting: str, icon: str) -> None:
        super().__init__(coordinator, key, name)
        self._setting = setting
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator.settings, self._setting))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_setting(self._setting, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_setting(self._setting, False)


class ArmedSwitch(VentilationEntity, SwitchEntity):
    """Système armé : modifiable seulement par les utilisateurs autorisés."""

    _attr_icon = "mdi:shield-check"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "systeme_arme", "Système armé")

    @property
    def is_on(self) -> bool:
        return self.coordinator.settings.armed

    @property
    def icon(self) -> str:
        return "mdi:shield-check" if self.is_on else "mdi:shield-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"raison_desarmement": self.coordinator.settings.disarm_reason}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_armed(True, self._context)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_armed(False, self._context)
