"""Capteurs : décision, mode, moyenne, fin de commande manuelle, journal."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import VentilationConfigEntry
from .entity import VentilationEntity
from .logic import ALL_LEVELS, SEASONS


async def async_setup_entry(
    hass: HomeAssistant, entry: VentilationConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            DecisionSensor(c),
            SeasonSensor(c),
            AverageSensor(c),
            OverrideEndSensor(c),
            LastEventSensor(c),
            CounterSensor(c, "nombre_ouvertures", "Nombre d'ouvertures", "ouvertures", "mdi:window-open-variant"),
            CounterSensor(c, "nombre_fermetures", "Nombre de fermetures", "fermetures", "mdi:window-closed-variant"),
            CounterSensor(c, "impulsions_ouvrir", "Impulsions OUVRIR envoyées", "impulsions_ouvrir", "mdi:gesture-tap"),
            CounterSensor(c, "impulsions_fermer", "Impulsions FERMER envoyées", "impulsions_fermer", "mdi:gesture-tap"),
        ]
    )


class DecisionSensor(VentilationEntity, SensorEntity):
    """Niveau gagnant du pipeline, avec la trace complète en attributs."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:sitemap"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "decision", "Décision")
        self._attr_options = [label for _, _, label in ALL_LEVELS]

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.label if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        d = c.data
        if d is None:
            return {}
        inp = c.inputs
        return {
            "priorite": d.priority,
            "cle": d.key,
            "raison": d.reason,
            "cible": d.target,
            "arme": c.settings.armed,
            "raison_desarmement": c.settings.disarm_reason,
            "meteo": inp.weather_reason if inp else None,
            "station_meteo": inp.weather_station_issue if inp else None,
            "ventilation": inp.ventilation.reason if inp else None,
            "fenetre_nocturne_debut": c.night.start.isoformat() if c.night else None,
            "fenetre_nocturne_fin": c.night.end.isoformat() if c.night else None,
            "derniere_impulsion_ouvrir": c.last_open_pulse.isoformat() if c.last_open_pulse else None,
            "derniere_impulsion_fermer": c.last_close_pulse.isoformat() if c.last_close_pulse else None,
            "trace": d.trace_dicts(),
            "entites": c.entity_map(),
            "en_mouvement": c.is_moving(),
        }


class SeasonSensor(VentilationEntity, SensorEntity):
    """Mode saisonnier actif."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = SEASONS
    _attr_icon = "mdi:thermometer-lines"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "mode_saison", "Mode saisonnier")

    @property
    def native_value(self) -> str:
        return self.coordinator.season

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"force": self.coordinator.settings.season_force}


class AverageSensor(VentilationEntity, SensorEntity):
    """Température extérieure moyenne sur 24 h (base du choix du mode)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "temperature_moyenne_24h", "Température extérieure moyenne 24 h")

    @property
    def native_value(self) -> float | None:
        avg = self.coordinator.avg_outdoor
        return round(avg, 2) if avg is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"echantillons": len(self.coordinator.samples)}


class OverrideEndSensor(VentilationEntity, SensorEntity):
    """Heure de retour en automatique après une commande manuelle."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "fin_commande_manuelle", "Fin de la commande manuelle")

    @property
    def native_value(self) -> datetime | None:
        ov = self.coordinator.override
        return ov.until if ov and ov.until > dt_util.utcnow() else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ov = self.coordinator.override
        return {"cible": ov.target, "utilisateur": ov.user} if ov else {}


class LastEventSensor(VentilationEntity, SensorEntity):
    """Dernier événement, avec les 20 derniers en attribut."""

    _attr_icon = "mdi:history"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "dernier_evenement", "Dernier événement")

    @property
    def native_value(self) -> str | None:
        ev = self.coordinator.events
        return ev[0]["message"][:250] if ev else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"journal": list(self.coordinator.events)}


class CounterSensor(VentilationEntity, SensorEntity):
    """Compteur de cycle de vie (ne diminue qu'en cas de remise à zéro)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "cycles"

    def __init__(self, coordinator, key: str, name: str, counter: str, icon: str) -> None:
        super().__init__(coordinator, key, name)
        self._counter = counter
        self._attr_icon = icon

    @property
    def native_value(self) -> int:
        return int(self.coordinator.counters.get(self._counter, 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"depuis": self.coordinator.counters.get("depuis")}
