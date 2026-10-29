"""Ventilation désenfumage : pilotage d'un ouvrant de désenfumage pour la ventilation."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import VentilationCoordinator

type VentilationConfigEntry = ConfigEntry[VentilationCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: VentilationConfigEntry) -> bool:
    """Configurer une installation."""
    coordinator = VentilationCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VentilationConfigEntry) -> bool:
    """Décharger une installation."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: VentilationConfigEntry) -> None:
    """Recharger après modification des options."""
    await hass.config_entries.async_reload(entry.entry_id)
