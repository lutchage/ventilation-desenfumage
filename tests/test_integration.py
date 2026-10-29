"""Tests de bout en bout dans une instance Home Assistant de test."""

from datetime import datetime, timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.ventilation_desenfumage.const import DOMAIN
from custom_components.ventilation_desenfumage.coordinator import VentilationCoordinator


class _Call:
    """Appel enregistré (même forme que ServiceCall pour les assertions)."""

    def __init__(self, entity_id: str) -> None:
        self.data = {"entity_id": entity_id}

PREFIX = "ventilation_desenfumage"
DATA = {
    "shelly_open": "switch.shelly_a",
    "shelly_close": "switch.shelly_b",
    "alarm_input": "binary_sensor.shelly_a_input",
    "fault_input": "binary_sensor.shelly_b_input",
    "door": "binary_sensor.ouvrant",
    "indoor_temp": "sensor.cage_temp",
    "outdoor_temp": "sensor.ws90_temp",
    "rain_rate": "sensor.ws90_rain",
    "wind_gust": "sensor.ws90_gust",
    "ups": "sensor.ups_status",
}


def _set_base_states(hass: HomeAssistant, outdoor: float = 12.0) -> None:
    hass.states.async_set("switch.shelly_a", "off")
    hass.states.async_set("switch.shelly_b", "off")
    hass.states.async_set("binary_sensor.shelly_a_input", "off")  # pas d'alarme
    hass.states.async_set("binary_sensor.shelly_b_input", "on")  # contact NF fermé = OK
    hass.states.async_set("binary_sensor.ouvrant", "off")
    hass.states.async_set("sensor.cage_temp", "18")
    hass.states.async_set("sensor.ws90_temp", str(outdoor))
    hass.states.async_set("sensor.ws90_rain", "0")
    hass.states.async_set("sensor.ws90_gust", "5", {"unit_of_measurement": "m/s"})
    hass.states.async_set("sensor.ups_status", "OL CHRG")


async def _setup(hass: HomeAssistant, freezer, monkeypatch, when: datetime, outdoor: float = 12.0):
    freezer.move_to(when)
    _set_base_states(hass, outdoor)
    calls_on: list[_Call] = []
    calls_off: list[_Call] = []

    async def _fake_switch(self, service, entity_id):
        (calls_on if service == "turn_on" else calls_off).append(_Call(entity_id))

    monkeypatch.setattr(VentilationCoordinator, "_switch", _fake_switch)
    entry = MockConfigEntry(domain=DOMAIN, title="Ventilation désenfumage", data=DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls_on, calls_off


def _decision(hass):
    return hass.states.get(f"sensor.{PREFIX}_decision")


def _local(hass, h, m, day=15, month=4):
    tz = dt_util.get_time_zone(hass.config.time_zone)
    return datetime(2026, month, day, h, m, tzinfo=tz)


async def _tick(hass, freezer, delta: timedelta):
    freezer.tick(delta)
    # la WS90 envoie ses données en continu : rafraîchir last_reported
    for eid in ("sensor.ws90_temp", "sensor.ws90_rain", "sensor.ws90_gust"):
        st = hass.states.get(eid)
        hass.states.async_set(eid, st.state, st.attributes)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_setup_default_closed(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    st = _decision(hass)
    assert st.state == "Par défaut (fermé)"
    assert hass.states.get(f"sensor.{PREFIX}_mode_saisonnier").state == "normal"
    assert hass.states.get(f"switch.{PREFIX}_systeme_arme").state == "on"
    # première décision : une impulsion FERMER
    assert [c.data["entity_id"] for c in on] == ["switch.shelly_b"]


async def test_normal_mode_daily_aeration(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 12, 29))
    on.clear()
    await _tick(hass, freezer, timedelta(minutes=2))  # 12:31
    assert _decision(hass).state == "Ventilation"
    assert [c.data["entity_id"] for c in on] == ["switch.shelly_a"]
    # interlock : FERMER relâché avant OUVRIR
    assert any(c.data["entity_id"] == "switch.shelly_b" for c in off)
    # pas de maintien en mode normal (la fenêtre se termine avec la temporisation)
    on.clear()
    await _tick(hass, freezer, timedelta(minutes=6))  # 12:37
    assert on == []
    await _tick(hass, freezer, timedelta(minutes=4))  # 12:41
    assert _decision(hass).state == "Par défaut (fermé)"
    assert [c.data["entity_id"] for c in on] == ["switch.shelly_b"]


async def test_weather_beats_manual_open(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    await hass.services.async_call("button", "press", {"entity_id": f"button.{PREFIX}_ouvrir"}, blocking=True)
    await hass.async_block_till_done()
    assert _decision(hass).state == "Commande manuelle"
    hass.states.async_set("sensor.ws90_rain", "1.2")
    await hass.async_block_till_done()
    assert _decision(hass).state == "Météo défavorable"
    # la pluie s'arrête : on reste fermé pendant le séchage
    hass.states.async_set("sensor.ws90_rain", "0")
    await hass.async_block_till_done()
    assert _decision(hass).state == "Météo défavorable"
    assert "Séchage" in _decision(hass).attributes["raison"]


async def test_unknown_movement_disarms(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    await _tick(hass, freezer, timedelta(minutes=10))  # au-delà du délai de resynchronisation
    hass.states.async_set("binary_sensor.ouvrant", "on")
    await hass.async_block_till_done()
    arme = hass.states.get(f"switch.{PREFIX}_systeme_arme")
    assert arme.state == "off"
    assert "Mouvement non commandé" in arme.attributes["raison_desarmement"]
    assert _decision(hass).state == "Système désarmé"
    # aucune commande tant que désarmé
    on.clear()
    await _tick(hass, freezer, timedelta(minutes=5))
    assert on == []
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("button", "press", {"entity_id": f"button.{PREFIX}_fermer"}, blocking=True)


async def test_commanded_movement_does_not_disarm(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    await _tick(hass, freezer, timedelta(minutes=10))
    await hass.services.async_call("button", "press", {"entity_id": f"button.{PREFIX}_ouvrir"}, blocking=True)
    await hass.async_block_till_done()
    await _tick(hass, freezer, timedelta(seconds=40))
    hass.states.async_set("binary_sensor.ouvrant", "on")
    await hass.async_block_till_done()
    assert hass.states.get(f"switch.{PREFIX}_systeme_arme").state == "on"
    # maintien toutes les 5 min pendant la commande manuelle
    on.clear()
    await _tick(hass, freezer, timedelta(minutes=5))
    assert [c.data["entity_id"] for c in on] == ["switch.shelly_a"]


async def test_alarm_disarms_and_blocks_rearm(hass, freezer, monkeypatch, hass_admin_user):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    hass.states.async_set("binary_sensor.shelly_a_input", "on")
    await hass.async_block_till_done()
    assert _decision(hass).state == "Alarme désenfumage"
    assert hass.states.get(f"switch.{PREFIX}_systeme_arme").state == "off"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": f"switch.{PREFIX}_systeme_arme"},
            blocking=True, context=Context(user_id=hass_admin_user.id),
        )


async def test_power_cut_and_maintenance(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    hass.states.async_set("switch.shelly_a", "unavailable")
    hass.states.async_set("switch.shelly_b", "unavailable")
    await hass.async_block_till_done()
    assert _decision(hass).state == "Maintenance"
    hass.states.async_set("sensor.ups_status", "OB DISCHRG")
    await hass.async_block_till_done()
    assert _decision(hass).state == "Coupure secteur"


async def test_fault_relay_closes(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    hass.states.async_set("binary_sensor.shelly_b_input", "off")  # contact NF ouvert
    await hass.async_block_till_done()
    await _tick(hass, freezer, timedelta(seconds=40))  # anti-rebond
    assert _decision(hass).state == "Défaut"


async def test_permission_required_to_arm(hass, freezer, monkeypatch, hass_admin_user, hass_read_only_user):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": f"switch.{PREFIX}_systeme_arme"},
            blocking=True, context=Context(user_id=hass_read_only_user.id),
        )
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": f"switch.{PREFIX}_systeme_arme"},
        blocking=True, context=Context(user_id=hass_admin_user.id),
    )
    assert hass.states.get(f"switch.{PREFIX}_systeme_arme").state == "off"


async def test_heat_mode_night_ventilation(hass, freezer, monkeypatch):
    # Été : moyenne > 20 °C, intérieur 27 °C, extérieur 22 °C la nuit
    when = _local(hass, 23, 30, day=15, month=7)
    entry, on, off = await _setup(hass, freezer, monkeypatch, when, outdoor=22.0)
    hass.states.async_set("sensor.cage_temp", "27")
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.{PREFIX}_mode_saisonnier").state == "canicule"
    attrs = _decision(hass).attributes
    start = dt_util.parse_datetime(attrs["fenetre_nocturne_debut"])
    end = dt_util.parse_datetime(attrs["fenetre_nocturne_fin"])
    now = dt_util.utcnow()
    assert start <= now < end
    assert _decision(hass).state == "Ventilation"
    assert [c.data["entity_id"] for c in on][-1] == "switch.shelly_a"
    # la cage est refroidie : arrêt et fermeture
    hass.states.async_set("sensor.cage_temp", "19.8")
    await hass.async_block_till_done()
    assert _decision(hass).state == "Par défaut (fermé)"
    assert "Cible atteinte" in _decision(hass).attributes["ventilation"]
    assert [c.data["entity_id"] for c in on][-1] == "switch.shelly_b"


async def test_station_failure(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    hass.states.async_set("sensor.ws90_gust", "unavailable")
    await hass.async_block_till_done()
    assert _decision(hass).state == "Panne station météo"
    hass.states.async_set("sensor.ws90_gust", "5", {"unit_of_measurement": "m/s"})
    await hass.async_block_till_done()
    assert _decision(hass).state == "Par défaut (fermé)"
    # plus de données pendant 20 min : station considérée en panne
    freezer.tick(timedelta(minutes=20))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert _decision(hass).state == "Panne station météo"
    assert "sans mise à jour" in _decision(hass).attributes["station_meteo"]


async def test_config_flow(hass):
    for eid in DATA.values():
        hass.states.async_set(eid, "0")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Ventilation désenfumage", **DATA}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["shelly_open"] == "switch.shelly_a"


async def test_movement_counters(hass, freezer, monkeypatch, hass_admin_user, hass_read_only_user):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    p = f"sensor.{PREFIX}_nombre_d"
    assert hass.states.get(f"{p}_ouvertures").state == "0"
    # un cycle complet
    hass.states.async_set("binary_sensor.ouvrant", "on")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.ouvrant", "off")
    await hass.async_block_till_done()
    # mouvement pendant une indisponibilité (maintenance) : compté au retour
    hass.states.async_set("binary_sensor.ouvrant", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.ouvrant", "on")
    await hass.async_block_till_done()
    # retour au même état après indisponibilité : pas compté
    hass.states.async_set("binary_sensor.ouvrant", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.ouvrant", "on")
    await hass.async_block_till_done()
    assert hass.states.get(f"{p}_ouvertures").state == "2"
    assert hass.states.get(f"sensor.{PREFIX}_nombre_de_fermetures").state == "1"
    assert int(hass.states.get(f"sensor.{PREFIX}_impulsions_fermer_envoyees").state) >= 1

    reset = {"entity_id": f"button.{PREFIX}_remise_a_zero_des_compteurs"}
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("button", "press", reset, blocking=True,
                                       context=Context(user_id=hass_read_only_user.id))
    await hass.services.async_call("button", "press", reset, blocking=True,
                                   context=Context(user_id=hass_admin_user.id))
    await hass.async_block_till_done()
    assert hass.states.get(f"{p}_ouvertures").state == "0"


async def test_card_entity_map(hass, freezer, monkeypatch):
    entry, on, off = await _setup(hass, freezer, monkeypatch, _local(hass, 9, 0))
    hass.states.async_set("sensor.ws90_temp", "12.5")  # nouvelle évaluation après l'enregistrement des entités
    await hass.async_block_till_done()
    ent = _decision(hass).attributes["entites"]
    assert ent["door"] == "binary_sensor.ouvrant"
    assert ent["armed_switch"] == f"switch.{PREFIX}_systeme_arme"
    assert ent["open_button"] == f"button.{PREFIX}_ouvrir"
    assert ent["close_button"] == f"button.{PREFIX}_fermer"
    assert ent["resume_button"] == f"button.{PREFIX}_retour_en_automatique"
    assert ent["season"] == f"sensor.{PREFIX}_mode_saisonnier"
