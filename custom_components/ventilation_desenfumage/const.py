"""Constantes de l'intégration Ventilation désenfumage."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ventilation_desenfumage"
DEFAULT_NAME = "Ventilation désenfumage"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

STORAGE_VERSION = 1
EVENT_NAME = f"{DOMAIN}_event"

# --- Entités configurées (config flow) ---
CONF_SHELLY_OPEN = "shelly_open"  # switch du Shelly A (OUVRIR)
CONF_SHELLY_CLOSE = "shelly_close"  # switch du Shelly B (FERMER)
CONF_ALARM = "alarm_input"  # entrée SW Shelly A (relais alarme X2.5)
CONF_FAULT = "fault_input"  # entrée SW Shelly B (relais défaut X2.8)
CONF_DOOR = "door"  # capteur d'ouverture BLU Door/Window
CONF_DOOR_TILT = "door_tilt"  # angle (optionnel)
CONF_INDOOR_TEMP = "indoor_temp"
CONF_INDOOR_HUMIDITY = "indoor_humidity"
CONF_OUTDOOR_TEMP = "outdoor_temp"
CONF_OUTDOOR_HUMIDITY = "outdoor_humidity"
CONF_RAIN_RATE = "rain_rate"
CONF_WIND_GUST = "wind_gust"
CONF_WIND_SPEED = "wind_speed"
CONF_PRECIP_RISK = "precip_risk"
CONF_UPS = "ups"

ENTITY_KEYS = [
    CONF_SHELLY_OPEN,
    CONF_SHELLY_CLOSE,
    CONF_ALARM,
    CONF_FAULT,
    CONF_DOOR,
    CONF_DOOR_TILT,
    CONF_INDOOR_TEMP,
    CONF_INDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMP,
    CONF_OUTDOOR_HUMIDITY,
    CONF_RAIN_RATE,
    CONF_WIND_GUST,
    CONF_WIND_SPEED,
    CONF_PRECIP_RISK,
    CONF_UPS,
]
REQUIRED_KEYS = [
    CONF_SHELLY_OPEN,
    CONF_SHELLY_CLOSE,
    CONF_ALARM,
    CONF_FAULT,
    CONF_DOOR,
    CONF_INDOOR_TEMP,
    CONF_OUTDOOR_TEMP,
    CONF_RAIN_RATE,
    CONF_WIND_GUST,
    CONF_UPS,
]

# --- Options techniques (options flow) ---
OPT_PULSE_S = "pulse_s"
OPT_KEEPALIVE_MIN = "keepalive_min"
OPT_CENTRAL_TIMER_MIN = "central_timer_min"
OPT_TRAVEL_S = "travel_s"
OPT_CLOSE_RETRY_MIN = "close_retry_min"
OPT_RESYNC_GRACE_S = "resync_grace_s"
OPT_STALE_MIN = "stale_min"
OPT_ALARM_INVERT = "alarm_invert"
OPT_FAULT_INVERT = "fault_invert"
OPT_DEBOUNCE_S = "debounce_s"
OPT_UPS_STATES = "ups_battery_states"
OPT_ALLOWED_USERS = "allowed_users"
OPT_NOTIFY = "notify"
OPT_MOVE_HOLD_S = "move_hold_s"

DEFAULT_OPTIONS = {
    OPT_PULSE_S: 1.0,
    OPT_KEEPALIVE_MIN: 5,
    OPT_CENTRAL_TIMER_MIN: 10,
    OPT_TRAVEL_S: 90,
    OPT_CLOSE_RETRY_MIN: 3,
    OPT_RESYNC_GRACE_S: 180,
    OPT_STALE_MIN: 15,
    OPT_ALARM_INVERT: False,
    OPT_FAULT_INVERT: False,
    OPT_DEBOUNCE_S: 5,
    OPT_UPS_STATES: "on,ob,on battery,on_battery,onbattery,discharging,sur batterie",
    OPT_ALLOWED_USERS: [],
    OPT_NOTIFY: True,
    OPT_MOVE_HOLD_S: 8,
}

UPDATE_INTERVAL_S = 30
SAMPLE_INTERVAL_MIN = 5
OPEN_ANGLE_MIN = 90  # angle au-delà duquel l'ouvrant est considéré grand ouvert
CLOSED_ANGLE_MAX = 3  # angle en dessous duquel il est considéré fermé
