"""Coordinateur : lit les capteurs, applique la logique et commande les Shelly."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.core import Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_event_date, get_astral_event_next
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALARM,
    CONF_DOOR,
    CONF_DOOR_TILT,
    CONF_FAULT,
    CONF_INDOOR_TEMP,
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
    ENTITY_KEYS,
    EVENT_NAME,
    OPT_ALARM_INVERT,
    OPT_ALLOWED_USERS,
    OPT_CENTRAL_TIMER_MIN,
    OPT_CLOSE_RETRY_MIN,
    OPT_DEBOUNCE_S,
    OPT_FAULT_INVERT,
    OPT_KEEPALIVE_MIN,
    OPT_NOTIFY,
    OPT_PULSE_S,
    OPT_RESYNC_GRACE_S,
    OPT_STALE_MIN,
    OPT_TRAVEL_S,
    OPT_UPS_STATES,
    SAMPLE_INTERVAL_MIN,
    STORAGE_VERSION,
    UPDATE_INTERVAL_S,
)
from .logic import (
    MOVE_CENTRAL_TIMER,
    MOVE_EXPECTED,
    SEASON_NORMAL,
    TARGET_CLOSE,
    TARGET_OPEN,
    Decision,
    Inputs,
    NightWindow,
    Override,
    Settings,
    VentRequest,
    average,
    classify_movement,
    compute_season,
    evaluate,
    evaluate_ventilation,
    night_window,
    ups_is_on_battery,
    wind_to_kmh,
)

_LOGGER = logging.getLogger(__name__)

_INVALID = (None, STATE_UNAVAILABLE, STATE_UNKNOWN, "")
MAX_CLOSE_RETRIES = 3
MANUAL_BLOCK_PRIORITY = 4  # boutons Ouvrir / Fermer bloqués à partir de ce niveau


class VentilationCoordinator(DataUpdateCoordinator[Decision]):
    """Cerveau de l'intégration."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_S),
        )
        self.conf: dict[str, Any] = dict(entry.data)
        self.opts: dict[str, Any] = {**DEFAULT_OPTIONS, **entry.options}
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        self._unsubs: list = []

        # État persistant
        self.settings = Settings()
        self.samples: list[tuple[datetime, float]] = []
        self.season: str = SEASON_NORMAL
        self.override: Override | None = None
        self.last_open_pulse: datetime | None = None
        self.last_close_pulse: datetime | None = None
        self.events: deque[dict] = deque(maxlen=20)
        self.counters: dict[str, Any] = _new_counters()
        self._last_door: str | None = None  # dernier état valide connu (on / off)

        # État volatil
        self.inputs: Inputs | None = None
        self.avg_outdoor: float | None = None
        self.night: NightWindow | None = None
        self.last_target: str | None = None
        self._vent_active = False
        self._vent_window_end: datetime | None = None
        self._last_rain: datetime | None = None
        self._last_wind: datetime | None = None
        self._fault_since: datetime | None = None
        self._close_retries = 0
        self._started_at = dt_util.utcnow()
        self._shellys_online_since: datetime | None = None
        self._entity_map: dict[str, str | None] | None = None

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Charger l'état sauvegardé et écouter les capteurs."""
        stored = await self._store.async_load() or {}
        self.settings = Settings.from_dict(stored.get("settings"))
        self.season = stored.get("season", SEASON_NORMAL)
        self.samples = [
            (dt, float(v))
            for t, v in stored.get("samples", [])
            if (dt := dt_util.parse_datetime(t)) is not None
        ]
        if ov := stored.get("override"):
            until = dt_util.parse_datetime(ov.get("until", ""))
            if until:
                self.override = Override(ov["target"], until, ov.get("user"))
        self.last_open_pulse = dt_util.parse_datetime(stored.get("last_open_pulse") or "")
        self.last_close_pulse = dt_util.parse_datetime(stored.get("last_close_pulse") or "")
        self.events.extend(stored.get("events", []))
        self.counters = {**_new_counters(), **(stored.get("counters") or {})}
        self._last_door = stored.get("last_door")
        door = self._st(CONF_DOOR)
        if self._last_door is None and door is not None and door.state in (STATE_ON, STATE_OFF):
            self._last_door = door.state

        watched = [self.conf[k] for k in ENTITY_KEYS if self.conf.get(k)]
        self._unsubs.append(async_track_state_change_event(self.hass, watched, self._on_state_change))

    async def async_shutdown(self) -> None:
        """Arrêter les écoutes et sauvegarder."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._to_store())
        await super().async_shutdown()

    def _to_store(self) -> dict:
        return {
            "settings": self.settings.as_dict(),
            "season": self.season,
            "samples": [(t.isoformat(), v) for t, v in self.samples],
            "override": (
                {"target": self.override.target, "until": self.override.until.isoformat(), "user": self.override.user}
                if self.override
                else None
            ),
            "last_open_pulse": self.last_open_pulse.isoformat() if self.last_open_pulse else None,
            "last_close_pulse": self.last_close_pulse.isoformat() if self.last_close_pulse else None,
            "events": list(self.events),
            "counters": self.counters,
            "last_door": self._last_door,
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._to_store, 10)

    # ------------------------------------------------------------------
    # Lecture des capteurs
    # ------------------------------------------------------------------

    def _st(self, key: str) -> State | None:
        eid = self.conf.get(key)
        return self.hass.states.get(eid) if eid else None

    def _online(self, key: str) -> bool:
        st = self._st(key)
        return st is not None and st.state != STATE_UNAVAILABLE

    def _float(self, key: str) -> float | None:
        st = self._st(key)
        if st is None or st.state in _INVALID:
            return None
        try:
            return float(st.state)
        except ValueError:
            return None

    def _bool(self, key: str) -> bool | None:
        st = self._st(key)
        if st is None or st.state not in (STATE_ON, STATE_OFF):
            return None
        return st.state == STATE_ON

    def float_value(self, key: str) -> float | None:
        """Valeur numérique d'une entité configurée (pour les entités exposées)."""
        return self._float(key)

    @callback
    def _update_online(self, now: datetime) -> bool:
        both = self._online(CONF_SHELLY_OPEN) and self._online(CONF_SHELLY_CLOSE)
        if both and self._shellys_online_since is None:
            self._shellys_online_since = now
        elif not both:
            self._shellys_online_since = None
        return both

    # ------------------------------------------------------------------
    # Événements
    # ------------------------------------------------------------------

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.utcnow()
        self._update_online(now)
        if event.data["entity_id"] == self.conf.get(CONF_DOOR):
            self._count_movement(event.data["new_state"])
            self._handle_door(event.data["old_state"], event.data["new_state"], now)
        self.hass.async_create_task(self.async_refresh())

    @callback
    def _handle_door(self, old: State | None, new: State | None, now: datetime) -> None:
        """Détecter un mouvement de l'ouvrant non commandé par Home Assistant."""
        if old is None or new is None:
            return
        if old.state not in (STATE_ON, STATE_OFF) or new.state not in (STATE_ON, STATE_OFF):
            return  # resynchronisation (capteur revenu en ligne)
        if old.state == new.state:
            return
        opened = new.state == STATE_ON
        grace = timedelta(seconds=self.opts[OPT_RESYNC_GRACE_S])

        if not self.settings.armed:
            return
        if now - self._started_at < grace:
            return
        if self._shellys_online_since is None or now - self._shellys_online_since < grace:
            return  # retour de maintenance ou de coupure
        if self._alarm_value():
            return  # traité par le niveau alarme
        if ups_is_on_battery(self._ups_state(), self.opts[OPT_UPS_STATES]):
            return  # la centrale ferme sur batterie (S1.6)

        kind = classify_movement(
            now,
            opened,
            self.last_open_pulse,
            self.last_close_pulse,
            self.opts[OPT_TRAVEL_S],
            self.opts[OPT_CENTRAL_TIMER_MIN],
        )
        if kind == MOVE_EXPECTED:
            return
        if kind == MOVE_CENTRAL_TIMER:
            still_wanted = self.data is not None and self.data.target == TARGET_OPEN
            if still_wanted and (
                self._vent_window_end is None or now < self._vent_window_end - timedelta(minutes=1)
            ):
                self._log_event(
                    "temporisation",
                    "Fermeture par la temporisation de la centrale (S2.3) alors que l'ouverture était "
                    "demandée : vérifier que l'impulsion de maintien remet bien le compteur à zéro.",
                    notify=True,
                )
            return

        local = dt_util.as_local(now)
        self._disarm(f"Mouvement non commandé : {'ouverture' if opened else 'fermeture'} le {local:%d.%m à %H:%M}")

    # ------------------------------------------------------------------
    # Construction des entrées
    # ------------------------------------------------------------------

    def _ups_state(self) -> str | None:
        st = self._st(CONF_UPS)
        return st.state if st else None

    def _alarm_value(self) -> bool | None:
        raw = self._bool(CONF_ALARM) if self._online(CONF_SHELLY_OPEN) else None
        if raw is None:
            return None
        return (not raw) if self.opts[OPT_ALARM_INVERT] else raw

    def _fault_value(self, now: datetime) -> bool | None:
        raw = self._bool(CONF_FAULT) if self._online(CONF_SHELLY_CLOSE) else None
        if raw is None:
            self._fault_since = None
            return None
        # Contact NF : entrée active = centrale OK
        fault = raw if self.opts[OPT_FAULT_INVERT] else not raw
        if not fault:
            self._fault_since = None
            return False
        if self._fault_since is None:
            self._fault_since = now
        return now - self._fault_since >= timedelta(seconds=self.opts[OPT_DEBOUNCE_S])

    def _weather_station(self, now: datetime) -> tuple[bool, str]:
        issues = []
        stale = timedelta(minutes=self.opts[OPT_STALE_MIN])
        for key, label in (
            (CONF_OUTDOOR_TEMP, "température extérieure"),
            (CONF_RAIN_RATE, "pluie"),
            (CONF_WIND_GUST, "rafales"),
        ):
            st = self._st(key)
            if st is None or st.state in _INVALID:
                issues.append(f"{label} indisponible")
                continue
            seen = getattr(st, "last_reported", None) or st.last_updated
            age = now - seen
            if age > stale:
                issues.append(f"{label} sans mise à jour depuis {int(age.total_seconds() // 60)} min")
        return (not issues, " ; ".join(issues))

    def _weather(self, now: datetime) -> tuple[bool, str]:
        s = self.settings
        reasons = []

        rain = self._float(CONF_RAIN_RATE)
        if rain is not None and rain > s.rain_threshold:
            self._last_rain = now
            reasons.append(f"Pluie ({rain:g} mm/h)")
        elif self._last_rain and now - self._last_rain < timedelta(minutes=s.rain_dry_min):
            end = dt_util.as_local(self._last_rain + timedelta(minutes=s.rain_dry_min))
            reasons.append(f"Séchage après pluie jusqu'à {end:%H:%M}")

        gust_st = self._st(CONF_WIND_GUST)
        gust = self._float(CONF_WIND_GUST)
        gust_kmh = wind_to_kmh(gust, gust_st.attributes.get("unit_of_measurement")) if gust is not None else None
        speed_st = self._st(CONF_WIND_SPEED)
        speed = self._float(CONF_WIND_SPEED)
        speed_kmh = wind_to_kmh(speed, speed_st.attributes.get("unit_of_measurement")) if speed is not None else None

        windy = (gust_kmh is not None and gust_kmh > s.gust_max_kmh) or (
            speed_kmh is not None and speed_kmh > s.wind_max_kmh
        )
        if windy:
            self._last_wind = now
            reasons.append(f"Vent (rafales {gust_kmh or 0:.0f} km/h, moyen {speed_kmh or 0:.0f} km/h)")
        elif self._last_wind and now - self._last_wind < timedelta(minutes=s.wind_hold_min):
            end = dt_util.as_local(self._last_wind + timedelta(minutes=s.wind_hold_min))
            reasons.append(f"Retombée du vent, attente jusqu'à {end:%H:%M}")

        risk = self._float(CONF_PRECIP_RISK)
        if risk is not None and risk > s.precip_risk_max:
            reasons.append(f"Risque de précipitations {risk:.0f} %")

        return (bool(reasons), " ; ".join(reasons))

    def _update_samples(self, now: datetime) -> None:
        temp = self._float(CONF_OUTDOOR_TEMP)
        if temp is not None and (
            not self.samples or now - self.samples[-1][0] >= timedelta(minutes=SAMPLE_INTERVAL_MIN)
        ):
            self.samples.append((now, temp))
            limit = now - timedelta(hours=24)
            self.samples = [(t, v) for t, v in self.samples if t >= limit]
            self._save()
        self.avg_outdoor = average(self.samples, now)
        new_season = compute_season(self.avg_outdoor, self.season, self.settings)
        if new_season != self.season:
            self._log_event("mode", f"Changement de mode : {self.season} → {new_season}")
            self.season = new_season
            self._save()

    def _night_window(self, local_now: datetime) -> NightWindow | None:
        today = local_now.date()
        sunset_today = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, today)
        sunset_yesterday = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, today - timedelta(days=1))
        if sunset_today is None or sunset_yesterday is None:
            return None
        window = night_window(
            local_now,
            sunset_today,
            sunset_yesterday,
            lambda dt: get_astral_event_next(self.hass, SUN_EVENT_SUNRISE, dt),
            self.settings,
        )
        return NightWindow(dt_util.as_local(window.start), dt_util.as_local(window.end))

    def _build_inputs(self, now: datetime) -> Inputs:
        local_now = dt_util.as_local(now)

        # Alarme : désarmement immédiat
        alarm = self._alarm_value()
        if alarm and self.settings.armed:
            self._disarm("Alarme désenfumage signalée par la centrale")

        # Fin de la commande manuelle
        if self.override and now >= self.override.until:
            self._log_event("manuel", "Fin de la commande manuelle, retour en automatique")
            self.override = None
            self._save()

        self._update_samples(now)
        self.night = self._night_window(local_now)
        vent: VentRequest = evaluate_ventilation(
            local_now,
            self.season,
            self.settings,
            self._float(CONF_INDOOR_TEMP),
            self._float(CONF_OUTDOOR_TEMP),
            self.night,
            self._vent_active,
        )
        self._vent_active = vent.want_open
        self._vent_window_end = vent.window_end

        station_ok, station_issue = self._weather_station(now)
        weather_bad, weather_reason = self._weather(now)

        self._update_online(now)
        return Inputs(
            now=now,
            armed=self.settings.armed,
            disarm_reason=self.settings.disarm_reason,
            shelly_open_online=self._online(CONF_SHELLY_OPEN),
            shelly_close_online=self._online(CONF_SHELLY_CLOSE),
            ups_on_battery=ups_is_on_battery(self._ups_state(), self.opts[OPT_UPS_STATES]),
            alarm=alarm,
            fault=self._fault_value(now),
            weather_station_ok=station_ok,
            weather_station_issue=station_issue,
            weather_bad=weather_bad,
            weather_reason=weather_reason,
            override=self.override,
            ventilation=vent,
        )

    # ------------------------------------------------------------------
    # Évaluation et commandes
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> Decision:
        async with self._lock:
            now = dt_util.utcnow()
            inputs = self._build_inputs(now)
            self.inputs = inputs
            decision = evaluate(inputs)
            previous = self.data
            if previous is None or previous.key != decision.key:
                self._log_event("decision", f"{decision.label} : {decision.reason}", notify=False)
                if decision.key == "defaut" and previous is not None:
                    self._log_event("defaut", decision.reason, notify=True)
            await self._apply(decision, inputs, now)
            return decision

    def _door_open(self) -> bool | None:
        return self._bool(CONF_DOOR)

    def _keepalive_due(self, decision: Decision, now: datetime) -> bool:
        if self.last_open_pulse is None:
            return True
        if now - self.last_open_pulse < timedelta(minutes=self.opts[OPT_KEEPALIVE_MIN]):
            return False
        # Inutile de prolonger si la fenêtre se termine avant la temporisation de la centrale
        end = self._vent_window_end if decision.key == "ventilation" else None
        if end is not None and end <= self.last_open_pulse + timedelta(minutes=self.opts[OPT_CENTRAL_TIMER_MIN]):
            return False
        return True

    async def _apply(self, decision: Decision, inp: Inputs, now: datetime) -> None:
        if decision.target is None:
            self.last_target = None
            self._close_retries = 0
            return

        if decision.target == TARGET_OPEN:
            self._close_retries = 0
            if self.last_target != TARGET_OPEN or self._keepalive_due(decision, now):
                await self._pulse(TARGET_OPEN, now)
        else:
            door_open = self._door_open()
            if self.last_target != TARGET_CLOSE:
                self._close_retries = 0
                await self._pulse(TARGET_CLOSE, now)
            elif door_open is True:
                retry = timedelta(minutes=self.opts[OPT_CLOSE_RETRY_MIN])
                if self.last_close_pulse is None or now - self.last_close_pulse >= retry:
                    if self._close_retries < MAX_CLOSE_RETRIES:
                        self._close_retries += 1
                        await self._pulse(TARGET_CLOSE, now)
                    elif self._close_retries == MAX_CLOSE_RETRIES:
                        self._close_retries += 1
                        self._log_event(
                            "fermeture",
                            "L'ouvrant reste ouvert malgré plusieurs ordres FERMER : vérifier l'installation.",
                            notify=True,
                        )
            elif door_open is False:
                self._close_retries = 0
        self.last_target = decision.target

    async def _switch(self, service: str, entity_id: str) -> None:
        """Appeler switch.turn_on / turn_off sur un Shelly."""
        await self.hass.services.async_call(
            "switch", service, {"entity_id": entity_id}, blocking=True, context=Context()
        )

    async def _pulse(self, target: str, now: datetime) -> None:
        """Envoyer une impulsion sur le Shelly correspondant (avec verrouillage)."""
        on_key, off_key = (
            (CONF_SHELLY_OPEN, CONF_SHELLY_CLOSE) if target == TARGET_OPEN else (CONF_SHELLY_CLOSE, CONF_SHELLY_OPEN)
        )
        on_eid, off_eid = self.conf[on_key], self.conf[off_key]
        if not self._online(on_key):
            _LOGGER.warning("Impulsion %s impossible : %s indisponible", target, on_eid)
            return
        try:
            if self._online(off_key):
                await self._switch("turn_off", off_eid)
            await self._switch("turn_on", on_eid)
        except HomeAssistantError as err:
            _LOGGER.error("Échec de l'impulsion %s : %s", target, err)
            return

        if target == TARGET_OPEN:
            self.last_open_pulse = now
            self.counters["impulsions_ouvrir"] += 1
        else:
            self.last_close_pulse = now
            self.counters["impulsions_fermer"] += 1
        self._save()
        _LOGGER.debug("Impulsion %s envoyée", target)

        async def _release(_now: datetime) -> None:
            try:
                await self._switch("turn_off", on_eid)
            except HomeAssistantError as err:
                _LOGGER.error("Impossible de relâcher %s : %s", on_eid, err)

        async_call_later(self.hass, self.opts[OPT_PULSE_S], _release)

    # ------------------------------------------------------------------
    # Actions depuis les entités
    # ------------------------------------------------------------------

    async def _check_permission(self, context: Context | None) -> str | None:
        """Vérifier qu'un utilisateur peut armer / désarmer. Renvoie son nom."""
        if context is None or context.user_id is None:
            return None  # automatisation ou système
        user = await self.hass.auth.async_get_user(context.user_id)
        if user is None:
            raise HomeAssistantError("Utilisateur inconnu")
        allowed: list[str] = self.opts.get(OPT_ALLOWED_USERS) or []
        ok = user.id in allowed if allowed else user.is_admin
        if not ok:
            raise HomeAssistantError(f"{user.name} n'est pas autorisé à effectuer cette action")
        return user.name

    async def _user_name(self, context: Context | None) -> str | None:
        if context is None or context.user_id is None:
            return None
        user = await self.hass.auth.async_get_user(context.user_id)
        return user.name if user else None

    async def async_set_armed(self, armed: bool, context: Context | None) -> None:
        """Armer ou désarmer (utilisateurs autorisés uniquement)."""
        name = await self._check_permission(context)
        if armed:
            if self._alarm_value():
                raise HomeAssistantError("Alarme désenfumage en cours : réarmement impossible")
            self.settings.armed = True
            self.settings.disarm_reason = None
            self.last_target = None
            self._log_event("arme", f"Système réarmé{f' par {name}' if name else ''}", notify=True)
        else:
            self._disarm(f"Désarmé manuellement{f' par {name}' if name else ''}")
        self._save()
        await self.async_refresh()

    @callback
    def _disarm(self, reason: str) -> None:
        if not self.settings.armed:
            return
        self.settings.armed = False
        self.settings.disarm_reason = reason
        self.last_target = None
        self._save()
        self._log_event("desarme", f"Système désarmé : {reason}", notify=True)

    async def async_manual(self, target: str, context: Context | None) -> None:
        """Commande manuelle OUVRIR / FERMER depuis le dashboard."""
        if not self.settings.armed:
            raise HomeAssistantError("Système désarmé : réarmer avant de commander l'ouvrant")
        if self.data is not None and self.data.priority >= MANUAL_BLOCK_PRIORITY:
            raise HomeAssistantError(f"Commande impossible : {self.data.label}")
        name = await self._user_name(context)
        until = dt_util.utcnow() + timedelta(hours=self.settings.override_hours)
        self.override = Override(target, until, name)
        self._log_event(
            "manuel",
            f"{'Ouverture' if target == TARGET_OPEN else 'Fermeture'} manuelle"
            f"{f' par {name}' if name else ''} jusqu'à {dt_util.as_local(until):%d.%m %H:%M}",
        )
        if target == TARGET_OPEN:
            self.last_target = None  # forcer une nouvelle impulsion
        self._save()
        await self.async_refresh()

    @callback
    def _count_movement(self, new: State | None) -> None:
        """Compter les mouvements réels de l'ouvrant (cycle de vie du moteur).

        Compare au dernier état valide connu : un mouvement fait pendant que le
        capteur était indisponible (maintenance, coupure) est compté à son retour.
        Tous les mouvements sont comptés, quelle que soit leur origine.
        """
        if new is None or new.state not in (STATE_ON, STATE_OFF):
            return
        if self._last_door is not None and new.state != self._last_door:
            key = "ouvertures" if new.state == STATE_ON else "fermetures"
            self.counters[key] += 1
        self._last_door = new.state
        self._save()

    async def async_reset_counters(self, context: Context | None) -> None:
        """Remettre les compteurs à zéro (utilisateurs autorisés, ex. moteur remplacé)."""
        name = await self._check_permission(context)
        self.counters = _new_counters()
        self._log_event("compteurs", f"Compteurs remis à zéro{f' par {name}' if name else ''}", notify=False)
        self._save()
        self.async_update_listeners()

    async def async_resume_auto(self) -> None:
        """Annuler la commande manuelle."""
        if self.override:
            self.override = None
            self._log_event("manuel", "Retour en automatique (annulation de la commande manuelle)")
            self._save()
        await self.async_refresh()

    async def async_update_setting(self, key: str, value: Any) -> None:
        """Modifier un réglage depuis une entité number / time / switch / select."""
        setattr(self.settings, key, value)
        self._save()
        await self.async_refresh()

    # ------------------------------------------------------------------
    # Journal et notifications
    # ------------------------------------------------------------------

    @callback
    def _log_event(self, kind: str, message: str, notify: bool = False) -> None:
        now = dt_util.now()
        self.events.appendleft({"time": now.isoformat(), "type": kind, "message": message})
        self.hass.bus.async_fire(EVENT_NAME, {"type": kind, "message": message})
        _LOGGER.info("%s", message)
        if notify and self.opts[OPT_NOTIFY]:
            persistent_notification.async_create(
                self.hass, f"{now:%d.%m.%Y %H:%M} – {message}", title=DEFAULT_NAME, notification_id=f"{DOMAIN}_{kind}"
            )
        self._save()

    # ------------------------------------------------------------------
    # Accesseurs pour les entités
    # ------------------------------------------------------------------

    def entity_map(self) -> dict[str, str | None]:
        """Entités utilisées par la carte graphique (sources + entités de l'intégration)."""
        if self._entity_map is None:
            reg = er.async_get(self.hass)
            uid = self.config_entry.entry_id

            def own(domain: str, key: str) -> str | None:
                return reg.async_get_entity_id(domain, DOMAIN, f"{uid}_{key}")

            mapping = {k: self.conf.get(k) for k in ENTITY_KEYS}
            mapping.update(
                armed_switch=own("switch", "systeme_arme"),
                ventilation_switch=own("switch", "ventilation"),
                open_button=own("button", "ouvrir"),
                close_button=own("button", "fermer"),
                resume_button=own("button", "retour_auto"),
                override_end=own("sensor", "fin_commande_manuelle"),
                season=own("sensor", "mode_saison"),
                average=own("sensor", "temperature_moyenne_24h"),
            )
            if all(mapping[k] for k in ("armed_switch", "open_button", "close_button")):
                self._entity_map = mapping  # mise en cache une fois tout enregistré
            return mapping
        return self._entity_map

    @property
    def door_tilt(self) -> float | None:
        return self._float(CONF_DOOR_TILT)


def _new_counters() -> dict[str, Any]:
    return {
        "ouvertures": 0,
        "fermetures": 0,
        "impulsions_ouvrir": 0,
        "impulsions_fermer": 0,
        "depuis": dt_util.now().isoformat(),
    }
