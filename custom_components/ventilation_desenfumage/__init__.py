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


async def async_register_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """Déclarer la carte comme ressource des tableaux de bord (mode « stockage »).

    Home Assistant attend que les ressources soient chargées avant d'afficher les
    cartes : on évite ainsi l'erreur « Configuration error » (élément personnalisé
    pas encore défini). Une ressource existante pour la carte est mise à jour
    (nouveau numéro de version) et les doublons sont supprimés.
    Renvoie False si les ressources ne sont pas gérables (mode YAML, Lovelace absent).
    """
    try:
        from homeassistant.components.lovelace.resources import ResourceStorageCollection
    except ImportError:  # pragma: no cover
        return False

    data = hass.data.get("lovelace")
    resources = getattr(data, "resources", None)
    if resources is None and isinstance(data, dict):  # anciennes versions de Home Assistant
        resources = data.get("resources")
    if not isinstance(resources, ResourceStorageCollection):
        return False

    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    mine = [item for item in resources.async_items() if str(item.get("url", "")).split("?")[0] == CARD_URL]
    if not mine:
        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.info("Carte ajoutée aux ressources des tableaux de bord : %s", url)
        return True

    first, *duplicates = mine
    if first.get("url") != url or first.get("type") != "module":
        await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
    for item in duplicates:
        await resources.async_delete_item(item["id"])
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Servir la carte graphique et la faire charger par le frontend."""
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
    url = f"{CARD_URL}?v={manifest.get('version', '0')}"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])

    try:
        if await async_register_lovelace_resource(hass, url):
            return
    except Exception:  # noqa: BLE001 - ne jamais bloquer l'intégration pour la carte
        _LOGGER.exception("Impossible d'ajouter la carte aux ressources des tableaux de bord")

    # Repli (tableaux de bord en YAML) : chargement en module supplémentaire
    if DATA_EXTRA_MODULE_URL in hass.data:
        add_extra_js_url(hass, url)
    _LOGGER.warning(
        "Tableaux de bord en mode YAML : pour éviter « Configuration error », ajouter la ressource %s "
        "(type module) dans la configuration Lovelace",
        url,
    )


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
