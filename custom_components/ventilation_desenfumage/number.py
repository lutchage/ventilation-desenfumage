"""Réglages numériques modifiables depuis le dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentilationConfigEntry
from .entity import VentilationEntity


@dataclass(frozen=True)
class _Num:
    key: str
    name: str
    setting: str
    min: float
    max: float
    step: float
    unit: str | None
    icon: str
    config: bool = True  # rangé dans « Configuration »
    integer: bool = False


KMH = "km/h"
MMH = "mm/h"

NUMBERS = [
    _Num("duree_commande_manuelle", "Durée de la commande manuelle", "override_hours", 0.5, 48, 0.5,
         UnitOfTime.HOURS, "mdi:timer-cog", config=False),
    # Choix du mode
    _Num("seuil_froid", "Seuil mode froid", "cold_threshold", -10, 15, 0.5, UnitOfTemperature.CELSIUS, "mdi:snowflake"),
    _Num("seuil_canicule", "Seuil mode canicule", "heat_threshold", 10, 35, 0.5, UnitOfTemperature.CELSIUS,
         "mdi:weather-sunny-alert"),
    _Num("hysteresis_mode", "Hystérésis du mode", "season_hysteresis", 0, 5, 0.5, UnitOfTemperature.CELSIUS,
         "mdi:arrow-expand-vertical"),
    # Canicule
    _Num("decalage_coucher", "Décalage après le coucher du soleil", "sunset_offset_min", -120, 240, 15,
         UnitOfTime.MINUTES, "mdi:weather-sunset-down", integer=True),
    _Num("duree_max_nuit", "Durée max ventilation nocturne", "night_max_hours", 0.5, 12, 0.5, UnitOfTime.HOURS,
         "mdi:weather-night"),
    _Num("ecart_min", "Écart min intérieur / extérieur", "delta_min", 0.5, 10, 0.5, UnitOfTemperature.CELSIUS,
         "mdi:thermometer-chevron-down"),
    _Num("hysteresis_ecart", "Hystérésis de l'écart", "delta_hysteresis", 0, 3, 0.1, UnitOfTemperature.CELSIUS,
         "mdi:arrow-expand-vertical"),
    _Num("temp_int_min", "Température intérieure min (canicule)", "indoor_min_heat", 15, 35, 0.5,
         UnitOfTemperature.CELSIUS, "mdi:home-thermometer"),
    _Num("temp_int_cible", "Température intérieure cible", "indoor_target", 12, 30, 0.5, UnitOfTemperature.CELSIUS,
         "mdi:home-thermometer-outline"),
    # Normal
    _Num("duree_aeration", "Durée de l'aération quotidienne", "aeration_duration_min", 1, 60, 1,
         UnitOfTime.MINUTES, "mdi:timer-outline", integer=True),
    # Météo
    _Num("seuil_pluie", "Seuil de pluie", "rain_threshold", 0, 5, 0.1, MMH, "mdi:weather-rainy"),
    _Num("sechage_pluie", "Attente après la pluie", "rain_dry_min", 0, 240, 5, UnitOfTime.MINUTES,
         "mdi:weather-partly-rainy", integer=True),
    _Num("rafale_max", "Rafales max", "gust_max_kmh", 10, 150, 1, KMH, "mdi:weather-windy"),
    _Num("vent_max", "Vent moyen max", "wind_max_kmh", 5, 120, 1, KMH, "mdi:weather-windy-variant"),
    _Num("attente_vent", "Attente après le vent", "wind_hold_min", 0, 120, 5, UnitOfTime.MINUTES,
         "mdi:timer-sand", integer=True),
    _Num("risque_precip_max", "Risque de précipitations max", "precip_risk_max", 0, 100, 5, "%",
         "mdi:weather-cloudy-alert"),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: VentilationConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(SettingNumber(entry.runtime_data, n) for n in NUMBERS)


class SettingNumber(VentilationEntity, NumberEntity):
    """Réglage numérique."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, desc: _Num) -> None:
        super().__init__(coordinator, desc.key, desc.name)
        self._desc = desc
        self._attr_native_min_value = desc.min
        self._attr_native_max_value = desc.max
        self._attr_native_step = desc.step
        self._attr_native_unit_of_measurement = desc.unit
        self._attr_icon = desc.icon
        if desc.config:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float:
        return getattr(self.coordinator.settings, self._desc.setting)

    async def async_set_native_value(self, value: float) -> None:
        if self._desc.integer:
            value = int(value)
        await self.coordinator.async_update_setting(self._desc.setting, value)
