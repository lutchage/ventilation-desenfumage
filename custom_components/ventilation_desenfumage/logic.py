"""Logique de décision pure (aucune dépendance à Home Assistant).

Ce module contient tout ce qui décide *quoi faire* :
- le choix du mode saisonnier (Froid / Normal / Canicule) ;
- la demande de ventilation (niveau 2) ;
- le pipeline de priorités (niveaux 0 à 10).

Le coordinateur (coordinator.py) se charge de lire les capteurs, de construire
un objet `Inputs` et d'exécuter la décision. Ce découpage permet de tester la
logique sans Home Assistant (voir tests/test_logic.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

SEASON_COLD = "froid"
SEASON_NORMAL = "normal"
SEASON_HEAT = "canicule"
SEASON_AUTO = "auto"
SEASONS = [SEASON_COLD, SEASON_NORMAL, SEASON_HEAT]

TARGET_OPEN = "ouvrir"
TARGET_CLOSE = "fermer"

# Niveaux du pipeline : (priorité, clé, libellé)
LEVEL_ALARM = (10, "alarme", "Alarme incendie")
LEVEL_DISARMED = (9, "desarme", "Arrêt de sécurité – vérification requise")
LEVEL_POWER_CUT = (8, "coupure", "Coupure de courant")
LEVEL_MAINTENANCE = (7, "maintenance", "Maintenance en cours")
LEVEL_FAULT = (6, "defaut", "Défaut de l'installation")
LEVEL_STATION = (5, "station", "Station météo hors service")
LEVEL_WEATHER = (4, "meteo", "Protection pluie / vent")
LEVEL_OVERRIDE = (3, "manuel", "Commande manuelle")
LEVEL_VENTILATION = (2, "ventilation", "Ventilation automatique")
LEVEL_DEFAULT = (0, "defaut_ferme", "Au repos – fermé")

ALL_LEVELS = [
    LEVEL_ALARM,
    LEVEL_DISARMED,
    LEVEL_POWER_CUT,
    LEVEL_MAINTENANCE,
    LEVEL_FAULT,
    LEVEL_STATION,
    LEVEL_WEATHER,
    LEVEL_OVERRIDE,
    LEVEL_VENTILATION,
    LEVEL_DEFAULT,
]


# --------------------------------------------------------------------------
# Réglages modifiables depuis le dashboard
# --------------------------------------------------------------------------


@dataclass
class Settings:
    """Réglages d'exploitation (persistés, modifiables par les entités)."""

    ventilation_enabled: bool = True
    armed: bool = True
    disarm_reason: str | None = None
    season_force: str = SEASON_AUTO

    # Commande manuelle
    override_hours: float = 4.0

    # Choix du mode (température extérieure moyenne sur 24 h)
    cold_threshold: float = 5.0
    heat_threshold: float = 20.0
    season_hysteresis: float = 1.0

    # Mode canicule : ventilation nocturne
    sunset_offset_min: int = 60
    night_max_hours: float = 4.0
    delta_min: float = 2.0
    delta_hysteresis: float = 0.5
    indoor_min_heat: float = 22.0
    indoor_target: float = 20.0

    # Mode normal : aération quotidienne
    aeration_time: str = "12:30:00"
    aeration_duration_min: int = 10

    # Plage interdite (option)
    quiet_enabled: bool = False
    quiet_start: str = "02:00:00"
    quiet_end: str = "05:00:00"

    # Météo
    rain_threshold: float = 0.0  # mm/h, pluie si strictement supérieur
    rain_dry_min: int = 30
    gust_max_kmh: float = 50.0
    wind_max_kmh: float = 35.0
    wind_hold_min: int = 15
    precip_risk_max: float = 70.0

    def as_dict(self) -> dict:
        """Sérialiser pour le stockage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> Settings:
        """Recharger depuis le stockage en ignorant les clés inconnues."""
        settings = cls()
        for key, value in (data or {}).items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        return settings


# --------------------------------------------------------------------------
# Outils horaires
# --------------------------------------------------------------------------


def parse_time(value: str | time) -> time:
    """Convertir 'HH:MM[:SS]' en objet time."""
    if isinstance(value, time):
        return value
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


def in_time_range(now: time, start: time, end: time) -> bool:
    """Vrai si `now` est dans [start, end[, en gérant le passage de minuit."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


# --------------------------------------------------------------------------
# Mode saisonnier
# --------------------------------------------------------------------------


def average(samples: list[tuple[datetime, float]], now: datetime, hours: float = 24) -> float | None:
    """Moyenne des échantillons des `hours` dernières heures."""
    limit = now - timedelta(hours=hours)
    values = [v for t, v in samples if t >= limit]
    if not values:
        return None
    return sum(values) / len(values)


def compute_season(avg: float | None, current: str | None, s: Settings) -> str:
    """Choisir le mode selon la moyenne, avec hystérésis.

    - Canicule si moyenne > seuil canicule ; on en sort sous (seuil - hyst).
    - Froid si moyenne < seuil froid ; on en sort au-dessus de (seuil + hyst).
    - Normal sinon.
    """
    if s.season_force in SEASONS:
        return s.season_force
    if avg is None:
        return current or SEASON_NORMAL

    hyst = s.season_hysteresis
    if current == SEASON_HEAT and avg >= s.heat_threshold - hyst:
        return SEASON_HEAT
    if current == SEASON_COLD and avg <= s.cold_threshold + hyst:
        return SEASON_COLD
    if avg > s.heat_threshold:
        return SEASON_HEAT
    if avg < s.cold_threshold:
        return SEASON_COLD
    return SEASON_NORMAL


# --------------------------------------------------------------------------
# Demande de ventilation (niveau 2)
# --------------------------------------------------------------------------


@dataclass
class VentRequest:
    """Résultat de la logique de ventilation."""

    want_open: bool
    reason: str
    window_end: datetime | None = None  # fin connue de l'ouverture (None = indéterminée)


@dataclass
class NightWindow:
    """Fenêtre de ventilation nocturne (mode canicule)."""

    start: datetime
    end: datetime


def night_window(
    now: datetime,
    sunset_today: datetime,
    sunset_yesterday: datetime,
    sunrise_after: callable,
    s: Settings,
) -> NightWindow:
    """Calculer la fenêtre nocturne qui contient `now` ou la dernière passée.

    `sunrise_after(dt)` doit renvoyer le premier lever du soleil après `dt`.
    """
    offset = timedelta(minutes=s.sunset_offset_min)
    start = sunset_today + offset
    if now < start:
        start = sunset_yesterday + offset
    end = min(start + timedelta(hours=s.night_max_hours), sunrise_after(start))
    return NightWindow(start, end)


def evaluate_ventilation(
    now: datetime,
    season: str,
    s: Settings,
    indoor_temp: float | None,
    outdoor_temp: float | None,
    night: NightWindow | None,
    was_active: bool,
) -> VentRequest:
    """Décider si la ventilation demande une ouverture."""
    if not s.ventilation_enabled:
        return VentRequest(False, "Ventilation désactivée")

    if season == SEASON_COLD:
        return VentRequest(False, "Mode froid : pas d'ouverture")

    if season == SEASON_NORMAL:
        start_t = parse_time(s.aeration_time)
        start = now.replace(hour=start_t.hour, minute=start_t.minute, second=start_t.second, microsecond=0)
        end = start + timedelta(minutes=s.aeration_duration_min)
        if start <= now < end:
            return VentRequest(True, f"Aération quotidienne jusqu'à {end:%H:%M}", end)
        return VentRequest(False, f"Mode normal : aération à {start:%H:%M}")

    # Mode canicule
    if night is None or not (night.start <= now < night.end):
        when = f" (prochaine fenêtre dès {night.start:%H:%M})" if night and now < night.start else ""
        return VentRequest(False, f"Mode canicule : hors fenêtre nocturne{when}")

    if s.quiet_enabled and in_time_range(now.time(), parse_time(s.quiet_start), parse_time(s.quiet_end)):
        return VentRequest(False, "Plage horaire interdite")

    if indoor_temp is None or outdoor_temp is None:
        return VentRequest(False, "Température intérieure ou extérieure indisponible")

    delta = indoor_temp - outdoor_temp
    if was_active:
        # Hystérésis : on reste ouvert tant que l'écart reste suffisant
        if indoor_temp <= s.indoor_target:
            return VentRequest(False, f"Cible atteinte ({indoor_temp:.1f} °C ≤ {s.indoor_target:.1f} °C)")
        if delta < s.delta_min - s.delta_hysteresis:
            return VentRequest(False, f"Écart insuffisant ({delta:.1f} °C)")
        return VentRequest(True, f"Rafraîchissement nocturne (écart {delta:.1f} °C)", None)

    if indoor_temp < s.indoor_min_heat:
        return VentRequest(False, f"Intérieur assez frais ({indoor_temp:.1f} °C < {s.indoor_min_heat:.1f} °C)")
    if indoor_temp <= s.indoor_target:
        return VentRequest(False, f"Cible atteinte ({indoor_temp:.1f} °C)")
    if delta < s.delta_min:
        return VentRequest(False, f"Écart insuffisant ({delta:.1f} °C < {s.delta_min:.1f} °C)")
    return VentRequest(True, f"Rafraîchissement nocturne (écart {delta:.1f} °C)", None)


# --------------------------------------------------------------------------
# Pipeline de priorités
# --------------------------------------------------------------------------


@dataclass
class Override:
    """Commande manuelle en cours."""

    target: str
    until: datetime
    user: str | None = None


@dataclass
class Inputs:
    """Photographie de l'installation à un instant donné."""

    now: datetime
    armed: bool = True
    disarm_reason: str | None = None

    shelly_open_online: bool = True
    shelly_close_online: bool = True
    ups_on_battery: bool | None = False

    alarm: bool | None = False
    fault: bool | None = False  # True = défaut centrale

    weather_station_ok: bool = True
    weather_station_issue: str = ""
    weather_bad: bool = False
    weather_reason: str = ""

    override: Override | None = None
    ventilation: VentRequest = field(default_factory=lambda: VentRequest(False, ""))


@dataclass
class TraceItem:
    """Une ligne de la trace de décision."""

    priority: int
    key: str
    label: str
    active: bool
    reason: str
    target: str | None


@dataclass
class Decision:
    """Décision gagnante et trace complète."""

    priority: int
    key: str
    label: str
    reason: str
    target: str | None  # None = aucun ordre envoyé
    trace: list[TraceItem]

    def trace_dicts(self) -> list[dict]:
        """Trace sérialisable (attribut d'entité)."""
        return [asdict(t) for t in self.trace]


def evaluate(inp: Inputs) -> Decision:
    """Parcourir les niveaux du plus prioritaire au moins prioritaire."""
    trace: list[TraceItem] = []

    def add(level: tuple, active: bool, reason: str, target: str | None) -> None:
        prio, key, label = level
        trace.append(TraceItem(prio, key, label, active, reason, target))

    shellys_offline = not inp.shelly_open_online and not inp.shelly_close_online
    one_offline = inp.shelly_open_online != inp.shelly_close_online

    # 10 - Alarme désenfumage : plus aucun ordre
    add(LEVEL_ALARM, bool(inp.alarm), "Alarme signalée par la centrale" if inp.alarm else "", None)

    # 9 - Système désarmé
    add(
        LEVEL_DISARMED,
        not inp.armed,
        (inp.disarm_reason or "Désarmé") if not inp.armed else "",
        None,
    )

    # 8 - Coupure secteur : Shelly hors ligne + onduleur sur batterie
    power_cut = shellys_offline and inp.ups_on_battery is True
    add(LEVEL_POWER_CUT, power_cut, "Shelly hors ligne et onduleur sur batterie" if power_cut else "", None)

    # 7 - Maintenance : Shelly hors ligne, secteur présent (ou état onduleur inconnu)
    maintenance = shellys_offline and inp.ups_on_battery is not True
    reason = ""
    if maintenance:
        reason = "Shelly hors ligne (interrupteur à clé)"
        if inp.ups_on_battery is None:
            reason += " – état onduleur inconnu"
    add(LEVEL_MAINTENANCE, maintenance, reason, None)

    # 6 - Défaut : centrale en défaut ou un seul Shelly hors ligne
    fault_reasons = []
    if inp.fault:
        fault_reasons.append("Défaut signalé par la centrale")
    if one_offline:
        missing = "OUVRIR" if not inp.shelly_open_online else "FERMER"
        fault_reasons.append(f"Shelly {missing} hors ligne")
    add(LEVEL_FAULT, bool(fault_reasons), " ; ".join(fault_reasons), TARGET_CLOSE)

    # 5 - Panne station météo
    add(LEVEL_STATION, not inp.weather_station_ok, inp.weather_station_issue, TARGET_CLOSE)

    # 4 - Météo défavorable
    add(LEVEL_WEATHER, inp.weather_bad, inp.weather_reason, TARGET_CLOSE)

    # 3 - Commande manuelle
    ov = inp.override
    ov_active = ov is not None and inp.now < ov.until
    add(
        LEVEL_OVERRIDE,
        ov_active,
        f"{'Ouverture' if ov and ov.target == TARGET_OPEN else 'Fermeture'} manuelle jusqu'à {ov.until:%d.%m %H:%M}"
        if ov_active
        else "",
        ov.target if ov_active else None,
    )

    # 2 - Ventilation
    add(LEVEL_VENTILATION, inp.ventilation.want_open, inp.ventilation.reason, TARGET_OPEN)

    # 0 - Par défaut
    add(LEVEL_DEFAULT, True, "Aucune demande d'ouverture", TARGET_CLOSE)

    winner = next(t for t in trace if t.active)
    return Decision(winner.priority, winner.key, winner.label, winner.reason, winner.target, trace)


# --------------------------------------------------------------------------
# Classement des mouvements de l'ouvrant
# --------------------------------------------------------------------------

MOVE_EXPECTED = "attendu"
MOVE_CENTRAL_TIMER = "temporisation"
MOVE_UNKNOWN = "inconnu"


def classify_movement(
    now: datetime,
    opened: bool,
    last_open_pulse: datetime | None,
    last_close_pulse: datetime | None,
    travel_s: float,
    central_timer_min: float,
    tolerance_s: float = 60,
) -> str:
    """Dire si un changement d'état de l'ouvrant était commandé.

    - ouverture attendue : dans les `travel_s + tolérance` après une impulsion OUVRIR ;
    - fermeture attendue : dans les `travel_s + tolérance` après une impulsion FERMER ;
    - fermeture par la temporisation de la centrale (S2.3) : environ
      `central_timer_min` après la dernière impulsion OUVRIR ;
    - sinon : mouvement inconnu.
    """
    window = timedelta(seconds=travel_s + tolerance_s)
    if opened:
        if last_open_pulse and timedelta(0) <= now - last_open_pulse <= window:
            return MOVE_EXPECTED
        return MOVE_UNKNOWN

    if last_close_pulse and timedelta(0) <= now - last_close_pulse <= window:
        return MOVE_EXPECTED
    if last_open_pulse:
        timer = timedelta(minutes=central_timer_min)
        elapsed = now - last_open_pulse
        if timer - timedelta(seconds=tolerance_s) <= elapsed <= timer + window:
            return MOVE_CENTRAL_TIMER
    return MOVE_UNKNOWN


# --------------------------------------------------------------------------
# Onduleur
# --------------------------------------------------------------------------

DEFAULT_UPS_BATTERY_STATES = "on,ob,on battery,on_battery,onbattery,discharging,sur batterie"


def ups_is_on_battery(state: str | None, tokens: str = DEFAULT_UPS_BATTERY_STATES) -> bool | None:
    """Interpréter l'état de l'onduleur.

    Accepte un binary_sensor (on = sur batterie) ou un capteur texte
    (par ex. NUT : « OB DISCHRG », « On Battery Battery Discharging »).
    Renvoie None si l'état est inconnu.
    """
    if state is None or state.lower() in ("unknown", "unavailable", ""):
        return None
    value = state.strip().lower()
    wanted = [t.strip().lower() for t in tokens.split(",") if t.strip()]
    if value in wanted:
        return True
    words = value.replace("_", " ").split()
    for token in wanted:
        if " " in token:
            if token in value:
                return True
        elif token in words and token != "on":
            # « on » seul n'est significatif qu'en valeur exacte (binary_sensor)
            return True
    return False


# --------------------------------------------------------------------------
# Conversion de vitesse de vent
# --------------------------------------------------------------------------

_WIND_FACTORS = {
    "km/h": 1.0,
    "kmh": 1.0,
    "m/s": 3.6,
    "mph": 1.609344,
    "kn": 1.852,
    "kt": 1.852,
    "knots": 1.852,
    "ft/s": 1.09728,
}


def wind_to_kmh(value: float, unit: str | None) -> float:
    """Convertir une vitesse de vent en km/h (unité inconnue = km/h)."""
    return value * _WIND_FACTORS.get((unit or "km/h").strip().lower(), 1.0)
