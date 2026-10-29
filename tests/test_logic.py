"""Tests de la logique pure (sans Home Assistant)."""

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

_PATH = Path(__file__).parents[1] / "custom_components" / "ventilation_desenfumage" / "logic.py"
_spec = importlib.util.spec_from_file_location("vd_logic", _PATH)
L = importlib.util.module_from_spec(_spec)
sys.modules["vd_logic"] = L
_spec.loader.exec_module(L)

NOW = datetime(2026, 7, 15, 23, 0)


def base(**kw):
    inp = L.Inputs(now=NOW)
    for k, v in kw.items():
        setattr(inp, k, v)
    return inp


# ---------------- Pipeline ----------------


def test_default_closed():
    d = L.evaluate(base())
    assert d.key == "defaut_ferme" and d.target == L.TARGET_CLOSE


def test_alarm_wins_everything():
    d = L.evaluate(base(alarm=True, armed=False, fault=True, weather_bad=True))
    assert d.priority == 10 and d.target is None


def test_disarmed_sends_nothing():
    d = L.evaluate(base(armed=False, disarm_reason="Mouvement inconnu"))
    assert d.priority == 9 and d.target is None and "Mouvement" in d.reason


def test_power_cut_vs_maintenance():
    d = L.evaluate(base(shelly_open_online=False, shelly_close_online=False, ups_on_battery=True))
    assert d.key == "coupure"
    d = L.evaluate(base(shelly_open_online=False, shelly_close_online=False, ups_on_battery=False))
    assert d.key == "maintenance"
    d = L.evaluate(base(shelly_open_online=False, shelly_close_online=False, ups_on_battery=None))
    assert d.key == "maintenance" and "inconnu" in d.reason


def test_single_shelly_offline_is_fault():
    d = L.evaluate(base(shelly_open_online=False))
    assert d.key == "defaut" and d.target == L.TARGET_CLOSE


def test_weather_beats_override_and_ventilation():
    ov = L.Override(L.TARGET_OPEN, NOW + timedelta(hours=2))
    vent = L.VentRequest(True, "x")
    d = L.evaluate(base(weather_bad=True, weather_reason="Pluie", override=ov, ventilation=vent))
    assert d.key == "meteo" and d.target == L.TARGET_CLOSE


def test_override_beats_ventilation_and_expires():
    vent = L.VentRequest(True, "x")
    ov = L.Override(L.TARGET_CLOSE, NOW + timedelta(hours=1))
    assert L.evaluate(base(override=ov, ventilation=vent)).target == L.TARGET_CLOSE
    ov = L.Override(L.TARGET_CLOSE, NOW - timedelta(minutes=1))
    assert L.evaluate(base(override=ov, ventilation=vent)).key == "ventilation"


def test_station_failure_closes():
    d = L.evaluate(base(weather_station_ok=False, weather_station_issue="Données anciennes"))
    assert d.key == "station" and d.target == L.TARGET_CLOSE


# ---------------- Saisons ----------------


def test_season_thresholds_and_hysteresis():
    s = L.Settings()
    assert L.compute_season(25, None, s) == L.SEASON_HEAT
    assert L.compute_season(12, None, s) == L.SEASON_NORMAL
    assert L.compute_season(2, None, s) == L.SEASON_COLD
    # hystérésis : reste canicule à 19.5, sort à 18.9
    assert L.compute_season(19.5, L.SEASON_HEAT, s) == L.SEASON_HEAT
    assert L.compute_season(18.9, L.SEASON_HEAT, s) == L.SEASON_NORMAL
    assert L.compute_season(5.8, L.SEASON_COLD, s) == L.SEASON_COLD
    assert L.compute_season(6.1, L.SEASON_COLD, s) == L.SEASON_NORMAL
    s.season_force = L.SEASON_COLD
    assert L.compute_season(30, None, s) == L.SEASON_COLD


def test_average_window():
    samples = [(NOW - timedelta(hours=30), 100.0), (NOW - timedelta(hours=1), 10.0), (NOW, 20.0)]
    assert L.average(samples, NOW) == 15.0


# ---------------- Ventilation ----------------


def _night(now):
    s = L.Settings()
    sunset_today = now.replace(hour=21, minute=15)
    sunset_yesterday = sunset_today - timedelta(days=1)
    return L.night_window(
        now, sunset_today, sunset_yesterday, lambda dt: (dt + timedelta(days=1)).replace(hour=5, minute=50), s
    )


def test_night_window_across_midnight():
    w = _night(datetime(2026, 7, 16, 1, 0))
    assert w.start == datetime(2026, 7, 15, 22, 15)
    assert w.end == datetime(2026, 7, 16, 2, 15)  # 4 h max avant le lever


def test_heat_mode_opens_when_useful():
    s = L.Settings()
    now = datetime(2026, 7, 15, 23, 0)
    w = _night(now)
    r = L.evaluate_ventilation(now, L.SEASON_HEAT, s, 26.0, 21.0, w, False)
    assert r.want_open
    r = L.evaluate_ventilation(now, L.SEASON_HEAT, s, 26.0, 25.0, w, False)
    assert not r.want_open  # écart 1 °C < 2 °C
    # hystérésis : reste ouvert avec écart 1.6 °C si déjà actif
    r = L.evaluate_ventilation(now, L.SEASON_HEAT, s, 26.0, 24.4, w, True)
    assert r.want_open
    r = L.evaluate_ventilation(now, L.SEASON_HEAT, s, 19.9, 15.0, w, True)
    assert not r.want_open  # cible atteinte


def test_heat_mode_outside_window_and_quiet():
    s = L.Settings()
    now = datetime(2026, 7, 15, 18, 0)
    assert not L.evaluate_ventilation(now, L.SEASON_HEAT, s, 28, 20, _night(now), False).want_open
    s.quiet_enabled = True
    s.quiet_start, s.quiet_end = "22:30:00", "23:30:00"
    now = datetime(2026, 7, 15, 23, 0)
    r = L.evaluate_ventilation(now, L.SEASON_HEAT, s, 28, 20, _night(now), False)
    assert not r.want_open and "interdite" in r.reason


def test_normal_mode_daily_aeration():
    s = L.Settings()
    r = L.evaluate_ventilation(datetime(2026, 4, 1, 12, 35), L.SEASON_NORMAL, s, 15, 12, None, False)
    assert r.want_open and r.window_end == datetime(2026, 4, 1, 12, 40)
    r = L.evaluate_ventilation(datetime(2026, 4, 1, 12, 40), L.SEASON_NORMAL, s, 15, 12, None, True)
    assert not r.want_open


def test_cold_and_disabled():
    s = L.Settings()
    assert not L.evaluate_ventilation(NOW, L.SEASON_COLD, s, 20, 0, None, False).want_open
    s.ventilation_enabled = False
    assert not L.evaluate_ventilation(datetime(2026, 4, 1, 12, 35), L.SEASON_NORMAL, s, 15, 12, None, False).want_open


# ---------------- Mouvements ----------------


def test_classify_movement():
    t0 = NOW
    c = L.classify_movement
    assert c(t0 + timedelta(seconds=40), True, t0, None, 90, 10) == L.MOVE_EXPECTED
    assert c(t0 + timedelta(minutes=5), True, t0, None, 90, 10) == L.MOVE_UNKNOWN
    assert c(t0 + timedelta(seconds=30), False, None, t0, 90, 10) == L.MOVE_EXPECTED
    assert c(t0 + timedelta(minutes=10, seconds=30), False, t0, None, 90, 10) == L.MOVE_CENTRAL_TIMER
    assert c(t0 + timedelta(minutes=4), False, t0, None, 90, 10) == L.MOVE_UNKNOWN
    assert c(t0, True, None, None, 90, 10) == L.MOVE_UNKNOWN


# ---------------- Divers ----------------


def test_ups_parsing():
    f = L.ups_is_on_battery
    assert f("on") is True and f("off") is False
    assert f("OB DISCHRG") is True
    assert f("On Battery Battery Discharging") is True
    assert f("Online Battery Charging") is False
    assert f("OL CHRG") is False
    assert f("unavailable") is None


def test_wind_conversion():
    assert L.wind_to_kmh(10, "m/s") == 36.0
    assert L.wind_to_kmh(10, "km/h") == 10
    assert L.wind_to_kmh(10, None) == 10
