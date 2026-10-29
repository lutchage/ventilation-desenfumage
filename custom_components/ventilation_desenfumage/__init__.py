"""Ventilation désenfumage : pilotage d'un ouvrant de désenfumage pour la ventilation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import VentilationCoordinator

_LOGGER = logging.getLogger(__name__)

type VentilationConfigEntry = ConfigEntry[VentilationCoordinator]

CARD_FILE = "ventilation-desenfumage-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Servir la carte graphique et la charger automatiquement dans le frontend."""
    if hass.data.get(f"{DOMAIN}_card"):
        return
    hass.data[f"{DOMAIN}_card"] = True
    if getattr(hass, "http", None) is None:
        return  # pas d'interface web (tests)
    try:
        from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
        from homeassistant.components.http import StaticPathConfig
    except ImportError:  # pragma: no cover
        return

    path = Path(__file__).parent / "frontend" / CARD_FILE
    manifest = await hass.async_add_executor_job(
        lambda: json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
    )
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    if DATA_EXTRA_MODULE_URL in hass.data:
        add_extra_js_url(hass, f"{CARD_URL}?v={manifest.get('version', '0')}")
    else:
        _LOGGER.warning("Frontend non chargé : ajouter %s comme ressource du tableau de bord", CARD_URL)


async def async_setup_entry(hass: HomeAssistant, entry: VentilationConfigEntry) -> bool:
    """Configurer une installation."""
    await _async_register_card(hass)
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
