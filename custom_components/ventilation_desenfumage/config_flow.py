"""Assistant de configuration et options."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ALARM,
    CONF_DOOR,
    CONF_DOOR_TILT,
    CONF_FAULT,
    CONF_INDOOR_HUMIDITY,
    CONF_INDOOR_TEMP,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMP,
    CONF_PRECIP_RISK,
    CONF_RAIN_RATE,
    CONF_SHELLY_CLOSE,
    CONF_SHELLY_OPEN,
    CONF_UPS,
    CONF_WIND_GUST,
    CONF_WIND_SPEED,
    DEFAULT_NAME,
    DEFAULT_OPTIONS,
    DOMAIN,
    OPT_ALARM_INVERT,
    OPT_ALLOWED_USERS,
    OPT_CENTRAL_TIMER_MIN,
    OPT_CLOSE_RETRY_MIN,
    OPT_DEBOUNCE_S,
    OPT_FAULT_INVERT,
    OPT_KEEPALIVE_MIN,
    OPT_MOVE_HOLD_S,
    OPT_NOTIFY_EVENTS,
    OPT_NOTIFY_TARGETS,
    OPT_NOTIFY_URL,
    OPT_OFFLINE_DEBOUNCE_MIN,
    OPT_STARTUP_MIN,
    NOTIFY_EVENT_TYPES,
    OPT_NOTIFY,
    OPT_PULSE_S,
    OPT_RESYNC_GRACE_S,
    OPT_STALE_MIN,
    OPT_TRAVEL_S,
    OPT_UPS_STATES,
)


def _ent(domain: str | list[str], device_class: str | None = None) -> selector.EntitySelector:
    cfg = selector.EntitySelectorConfig(domain=domain)
    if device_class:
        cfg = selector.EntitySelectorConfig(domain=domain, device_class=device_class)
    return selector.EntitySelector(cfg)


def _entities_schema(defaults: dict[str, Any]) -> vol.Schema:
    def req(key):
        return vol.Required(key, default=defaults[key]) if key in defaults else vol.Required(key)

    def opt(key):
        return (
            vol.Optional(key, description={"suggested_value": defaults[key]})
            if defaults.get(key)
            else vol.Optional(key)
        )

    return vol.Schema(
        {
            req(CONF_SHELLY_OPEN): _ent("switch"),
            req(CONF_SHELLY_CLOSE): _ent("switch"),
            req(CONF_ALARM): _ent("binary_sensor"),
            req(CONF_FAULT): _ent("binary_sensor"),
            req(CONF_DOOR): _ent("binary_sensor"),
            opt(CONF_DOOR_TILT): _ent("sensor"),
            req(CONF_INDOOR_TEMP): _ent("sensor", "temperature"),
            opt(CONF_INDOOR_HUMIDITY): _ent("sensor", "humidity"),
            req(CONF_OUTDOOR_TEMP): _ent("sensor", "temperature"),
            opt(CONF_OUTDOOR_HUMIDITY): _ent("sensor", "humidity"),
            req(CONF_RAIN_RATE): _ent("sensor"),
            req(CONF_WIND_GUST): _ent("sensor"),
            opt(CONF_WIND_SPEED): _ent("sensor"),
            opt(CONF_PRECIP_RISK): _ent("sensor"),
            req(CONF_UPS): _ent(["binary_sensor", "sensor"]),
        }
    )


class VentilationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Assistant de configuration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_SHELLY_OPEN] == user_input[CONF_SHELLY_CLOSE]:
                errors["base"] = "same_shelly"
            else:
                await self.async_set_unique_id(user_input[CONF_SHELLY_OPEN])
                self._abort_if_unique_id_configured()
                name = user_input.pop(CONF_NAME, DEFAULT_NAME)
                return self.async_create_entry(title=name, data=user_input)

        schema = vol.Schema({vol.Required(CONF_NAME, default=DEFAULT_NAME): str}).extend(
            _entities_schema({}).schema
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Changer les entités sans supprimer l'intégration."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_SHELLY_OPEN] == user_input[CONF_SHELLY_CLOSE]:
                errors["base"] = "same_shelly"
            else:
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id="reconfigure", data_schema=_entities_schema(dict(entry.data)), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VentilationOptionsFlow()


class VentilationOptionsFlow(OptionsFlow):
    """Options techniques (rarement modifiées)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        cur = {**DEFAULT_OPTIONS, **self.config_entry.options}
        users = [
            selector.SelectOptionDict(value=u.id, label=u.name or u.id)
            for u in await self.hass.auth.async_get_users()
            if not u.system_generated and u.is_active
        ]

        def num(lo, hi, step, unit):
            return selector.NumberSelector(
                selector.NumberSelectorConfig(min=lo, max=hi, step=step, unit_of_measurement=unit,
                                              mode=selector.NumberSelectorMode.BOX)
            )

        notify_services = sorted(
            name
            for name in self.hass.services.async_services().get("notify", {})
            if name not in ("send_message", "persistent_notification")
        )
        targets = [selector.SelectOptionDict(value=n, label=f"notify.{n}") for n in notify_services]
        events = [selector.SelectOptionDict(value=k, label=v) for k, v in NOTIFY_EVENT_TYPES.items()]

        schema = vol.Schema(
            {
                vol.Required(OPT_NOTIFY_TARGETS, default=cur[OPT_NOTIFY_TARGETS]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=targets, multiple=True, custom_value=True)
                ),
                vol.Required(OPT_NOTIFY_EVENTS, default=cur[OPT_NOTIFY_EVENTS]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=events, multiple=True)
                ),
                vol.Required(OPT_NOTIFY_URL, default=cur[OPT_NOTIFY_URL]): str,
                vol.Required(OPT_ALLOWED_USERS, default=cur[OPT_ALLOWED_USERS]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=users, multiple=True)
                ),
                vol.Required(OPT_PULSE_S, default=cur[OPT_PULSE_S]): num(0.2, 10, 0.1, "s"),
                vol.Required(OPT_KEEPALIVE_MIN, default=cur[OPT_KEEPALIVE_MIN]): num(1, 30, 1, "min"),
                vol.Required(OPT_CENTRAL_TIMER_MIN, default=cur[OPT_CENTRAL_TIMER_MIN]): num(1, 120, 1, "min"),
                vol.Required(OPT_TRAVEL_S, default=cur[OPT_TRAVEL_S]): num(5, 600, 5, "s"),
                vol.Required(OPT_MOVE_HOLD_S, default=cur[OPT_MOVE_HOLD_S]): num(3, 60, 1, "s"),
                vol.Required(OPT_CLOSE_RETRY_MIN, default=cur[OPT_CLOSE_RETRY_MIN]): num(1, 30, 1, "min"),
                vol.Required(OPT_RESYNC_GRACE_S, default=cur[OPT_RESYNC_GRACE_S]): num(30, 900, 10, "s"),
                vol.Required(OPT_STALE_MIN, default=cur[OPT_STALE_MIN]): num(2, 120, 1, "min"),
                vol.Required(OPT_STARTUP_MIN, default=cur[OPT_STARTUP_MIN]): num(0, 30, 1, "min"),
                vol.Required(OPT_OFFLINE_DEBOUNCE_MIN, default=cur[OPT_OFFLINE_DEBOUNCE_MIN]): num(0, 30, 1, "min"),
                vol.Required(OPT_DEBOUNCE_S, default=cur[OPT_DEBOUNCE_S]): num(0, 120, 1, "s"),
                vol.Required(OPT_ALARM_INVERT, default=cur[OPT_ALARM_INVERT]): bool,
                vol.Required(OPT_FAULT_INVERT, default=cur[OPT_FAULT_INVERT]): bool,
                vol.Required(OPT_UPS_STATES, default=cur[OPT_UPS_STATES]): str,
                vol.Required(OPT_NOTIFY, default=cur[OPT_NOTIFY]): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
