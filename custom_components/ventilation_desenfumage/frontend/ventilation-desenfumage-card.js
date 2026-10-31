/*
 * Carte « Ventilation désenfumage » pour Home Assistant.
 *
 * Configuration minimale :
 *   type: custom:ventilation-desenfumage-card
 *   entity: sensor.ventilation_desenfumage_decision
 *
 * Toutes les autres entités (capteur d'ouverture, températures, météo, boutons…)
 * sont lues dans l'attribut « entites » du capteur de décision.
 */

const CARD_VERSION = "0.5.0";

const MAX_ANGLE = 120; // ouverture maximale de la coupole (°)
const MANUAL_BLOCK_PRIORITY = 4; // boutons Ouvrir / Fermer bloqués à partir de ce niveau

const LEVEL_COLORS = {
  alarme: "var(--error-color, #db4437)",
  desarme: "var(--error-color, #db4437)",
  coupure: "var(--warning-color, #ffa600)",
  maintenance: "var(--info-color, #039be5)",
  defaut: "var(--warning-color, #ffa600)",
  station: "var(--warning-color, #ffa600)",
  meteo: "var(--info-color, #039be5)",
  manuel: "var(--primary-color, #03a9f4)",
  ventilation: "var(--success-color, #43a047)",
  defaut_ferme: "var(--secondary-text-color, #727272)",
};

const SHORT_LABEL = {
  alarme: "Alarme", desarme: "Arrêt", coupure: "Courant", maintenance: "Maint.", defaut: "Défaut",
  station: "Station", meteo: "Météo", manuel: "Manuel", ventilation: "Ventil.", defaut_ferme: "Repos",
};

const SEASON_LABEL = { froid: "Froid", normal: "Normal", canicule: "Canicule" };
const SEASON_COLOR = { froid: "#1e88e5", normal: "#00897b", canicule: "#fb8c00" };
const SEASON_ICON = { froid: "mdi:snowflake", normal: "mdi:weather-partly-cloudy", canicule: "mdi:white-balance-sunny" };

// Géométrie de la scène (viewBox 400 x 260) : coupe de l'immeuble du milieu du
// niveau 3 jusqu'au toit plat. Escalier montant de gauche à droite jusqu'au
// niveau 4, coupole au centre gauche avec charnière à gauche.
const ROOF_Y = 104; // dessus de la dalle du toit
const FLOOR4_Y = 184; // dessus de la dalle du niveau 4
const DOME_L = 112; // bord gauche de la costière = charnière
const DOME_R = 188; // bord droit de la costière
const DOME_Y = 86; // haut de la costière (appui de la coupole)
const DOME_H = 26; // hauteur de la coupole

function num(st) {
  if (!st || ["unknown", "unavailable", ""].includes(st.state)) return null;
  const v = parseFloat(st.state);
  return Number.isFinite(v) ? v : null;
}

function fmt(v, unit, digits = 1) {
  return v === null ? "–" : `${v.toFixed(digits)}${unit}`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function isArmedFor(hass, ent) {
  const s = ent && ent.armed_switch ? hass.states[ent.armed_switch] : null;
  return s ? s.state === "on" : true;
}

class VentilationDesenfumageCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Indiquer l'entité du capteur de décision (entity: sensor.…_decision)");
    }
    this._config = { show_pipeline: true, show_buttons: true, ...config };
    this._lastKey = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  static getStubConfig(hass) {
    const id = Object.keys(hass.states).find(
      (e) => e.startsWith("sensor.") && hass.states[e].attributes && hass.states[e].attributes.trace && e.endsWith("_decision")
    );
    return { entity: id || "sensor.ventilation_desenfumage_decision" };
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    this._hass = hass;
    const key = this._renderKey(hass);
    if (key === this._lastKey) return;
    this._lastKey = key;
    this._render();
  }

  // Ne redessiner que si une entité utile a changé
  _renderKey(hass) {
    const dec = hass.states[this._config.entity];
    if (!dec) return "missing";
    const ids = Object.values(dec.attributes.entites || {});
    ids.push(this._config.entity, "sun.sun");
    return ids.map((id) => {
      const s = hass.states[id];
      return s ? `${s.state}|${s.last_updated}` : "-";
    }).join(";");
  }

  _st(key) {
    const dec = this._hass.states[this._config.entity];
    const id = dec && dec.attributes.entites ? dec.attributes.entites[key] : null;
    return id ? this._hass.states[id] : undefined;
  }

  _press(key, confirmText) {
    const dec = this._hass.states[this._config.entity];
    const id = dec.attributes.entites[key];
    if (!id) return;
    if (confirmText && !window.confirm(confirmText)) return;
    this._hass.callService("button", "press", { entity_id: id }).catch((err) => {
      window.alert(err && err.message ? err.message : String(err));
    });
  }

  _moreInfo(key) {
    const dec = this._hass.states[this._config.entity];
    const id = key === "__decision" ? this._config.entity : dec.attributes.entites[key];
    if (!id) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: id }, bubbles: true, composed: true }));
  }

  _render() {
    const hass = this._hass;
    const root = this.shadowRoot;
    const dec = hass.states[this._config.entity];
    if (!dec) {
      root.innerHTML = `<ha-card><div class="warn">Entité introuvable : ${esc(this._config.entity)}</div></ha-card>`;
      return;
    }
    const a = dec.attributes;
    const ent = a.entites || {};
    const key = a.cle || "defaut_ferme";
    const color = LEVEL_COLORS[key] || LEVEL_COLORS.defaut_ferme;

    // --- État de l'ouvrant
    const door = this._st("door");
    const doorKnown = door && ["on", "off"].includes(door.state);
    const isOpen = doorKnown && door.state === "on";
    const tilt = num(this._st("door_tilt"));
    let angle = 0;
    if (isOpen) angle = tilt !== null ? Math.max(15, Math.min(MAX_ANGLE, tilt)) : 45;
    let doorText = !doorKnown ? "État inconnu" : isOpen ? (tilt !== null ? `Ouvert ${Math.round(tilt)}°` : "Ouvert") : "Fermé";

    // --- Mesures
    const tIn = num(this._st("indoor_temp"));
    const hIn = num(this._st("indoor_humidity"));
    const tOut = num(this._st("outdoor_temp"));
    const hOut = num(this._st("outdoor_humidity"));
    const rain = num(this._st("rain_rate"));
    const gustSt = this._st("wind_gust");
    const gust = num(gustSt);
    const gustUnit = gustSt ? gustSt.attributes.unit_of_measurement || "" : "";
    const raining = rain !== null && rain > 0;
    const trace = Array.isArray(a.trace) ? a.trace : [];
    const meteoActive = trace.some((t) => t.key === "meteo" && t.active);
    const windy = meteoActive && /vent/i.test(a.meteo || "");
    const alarm = key === "alarme";
    const sun = hass.states["sun.sun"];
    const night = sun ? sun.state === "below_horizon" : false;

    // --- Boutons manuels : bloqués si système désarmé ou niveau prioritaire actif
    const prio = Number(a.priorite ?? 0);
    const moving = a.en_mouvement === true;
    const manualOk = isArmedFor(hass, ent) && prio < MANUAL_BLOCK_PRIORITY && !moving;
    const manualWhy = manualOk ? "" : moving ? "Ouvrant en mouvement" : `Commande impossible : ${dec.state}`;

    // --- Chips
    const armed = hass.states[ent.armed_switch];
    const isArmed = armed ? armed.state === "on" : true;
    const season = hass.states[ent.season];
    const seasonVal = season ? season.state : null;
    const avg = num(hass.states[ent.average]);
    const ovEnd = hass.states[ent.override_end];
    let ovText = null;
    if (ovEnd && !["unknown", "unavailable"].includes(ovEnd.state)) {
      const d = new Date(ovEnd.state);
      if (!isNaN(d)) ovText = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }

    if (a.en_mouvement === true) doorText = `En mouvement${tilt !== null ? ` · ${Math.round(tilt)}°` : ""}`;

    // --- Coupole : rotation autour de la charnière gauche, le côté droit se soulève
    const rad = (angle * Math.PI) / 180;
    const arm = 0.55 * (DOME_R - DOME_L); // point d'attache du vérin sur le cadre
    const jackTop = { x: DOME_L + arm * Math.cos(rad), y: DOME_Y - arm * Math.sin(rad) };
    const domeW = DOME_R - DOME_L;
    // Escalier : du milieu du niveau 3 (bas de la vue) au niveau 4, de gauche à droite
    const steps = [];
    let sx = 34, sy = 260;
    for (let i = 0; i < 8; i++) { steps.push(`${sx},${sy}`); sy -= 10; steps.push(`${sx},${sy}`); sx += 22; }
    steps.push(`${sx},${sy}`);
    const stairEndX = sx;

    const ladder = trace
      .map((t) => {
        const win = t.key === key;
        const c = LEVEL_COLORS[t.key] || LEVEL_COLORS.defaut_ferme;
        if (win) {
          return `<div class="lvl win" style="--c:${c}" data-mi="__decision">
            <div class="wh"><span class="p">${t.priority}</span><span class="n">${esc(t.label)}</span></div>
            ${t.reason ? `<div class="r">${esc(t.reason)}</div>` : ""}</div>`;
        }
        return `<div class="lvl ${t.active ? "on" : ""}" style="--c:${c}" title="${esc(t.reason || "")}">
          <span class="p">${t.priority}</span><span class="n">${esc(t.label)}</span></div>`;
      })
      .join("");
    const seasonColor = SEASON_COLOR[seasonVal] || "var(--secondary-text-color,#727272)";
    const armedColor = isArmed ? "var(--success-color,#43a047)" : "var(--error-color,#db4437)";

    root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card class="${alarm ? "alarm" : ""}">
        <div class="head" data-mi="__decision">
          <div class="badge" style="background:${color}"><ha-icon icon="${isOpen ? "mdi:window-open-variant" : "mdi:window-closed-variant"}"></ha-icon></div>
          <div class="title">
            <div class="t1">${esc(this._config.title || "Ouvrant cage d'escalier")}</div>
          </div>
        </div>

        <div class="status">
          <div class="pill" style="--c:${seasonColor}" data-mi="season">
            <ha-icon icon="${SEASON_ICON[seasonVal] || "mdi:calendar"}"></ha-icon>
            <div><div class="pl">Mode</div><div class="pv">${esc(SEASON_LABEL[seasonVal] || "–")}</div>
            ${avg !== null ? `<div class="ps">moy. 24 h ${avg.toFixed(1)}°</div>` : ""}</div>
          </div>
          <div class="pill" style="--c:${armedColor}" data-mi="armed_switch">
            <ha-icon icon="${isArmed ? "mdi:shield-check" : "mdi:shield-off"}"></ha-icon>
            <div><div class="pl">Système</div><div class="pv">${isArmed ? "Armé" : "Désarmé"}</div></div>
          </div>
        </div>

        <div class="body"><div class="main">

        <svg class="scene" viewBox="0 0 400 260" role="img" aria-label="${esc(doorText)}">
          <defs>
            <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="${night ? "#1b2440" : "#9fd3f5"}"/>
              <stop offset="1" stop-color="${night ? "#2e3b63" : "#dff1fc"}"/>
            </linearGradient>
          </defs>

          <rect x="0" y="0" width="400" height="${ROOF_Y}" fill="url(#sky)" opacity="0.55"/>
          ${night
            ? `<circle cx="24" cy="22" r="11" fill="#f4f1d0"/><circle cx="29" cy="18" r="10" fill="#2a3659" opacity="0.9"/>`
            : `<circle cx="24" cy="22" r="12" fill="#ffc94a"/>`}

          ${windy ? `<g class="wind">
              <path d="M60 84 Q90 76 120 84" /><path d="M136 14 Q176 4 216 14" /><path d="M120 54 Q150 46 180 54" />
            </g>` : ""}

          ${raining ? `<g class="rain">${[20, 70, 100, 140, 210, 250, 300, 340, 380].map((x, i) =>
            `<line x1="${x}" y1="${-10 - (i % 3) * 25}" x2="${x - 6}" y2="${4 - (i % 3) * 25}" style="animation-delay:${(i * 0.17).toFixed(2)}s"/>`).join("")}</g>` : ""}

          <!-- intérieur : niveau 4 et moitié du niveau 3 -->
          <rect x="22" y="${ROOF_Y}" width="356" height="${260 - ROOF_Y}" class="inside"/>
          <text x="32" y="${FLOOR4_Y - 6}" class="cap">Niveau 4</text>
          <text x="${stairEndX + 20}" y="${FLOOR4_Y + 26}" class="cap">Niveau 3</text>

          <!-- escalier (monte de gauche à droite jusqu'au niveau 4) -->
          <polyline class="stairs" points="${steps.join(" ")}"/>

          <!-- dalles : niveau 4 (trémie de l'escalier) et toit (trémie de la coupole) -->
          <polyline class="slab" points="${stairEndX},${FLOOR4_Y + 5} 378,${FLOOR4_Y + 5}"/>
          <polyline class="roof" points="16,${ROOF_Y + 5} ${DOME_L},${ROOF_Y + 5}"/>
          <polyline class="roof" points="${DOME_R},${ROOF_Y + 5} 384,${ROOF_Y + 5}"/>
          <!-- façades et acrotères -->
          <polyline class="wall" points="20,${ROOF_Y - 12} 20,260"/>
          <polyline class="wall" points="380,${ROOF_Y - 12} 380,260"/>
          <!-- costière -->
          <polyline class="curb" points="${DOME_L + 3},${ROOF_Y + 9} ${DOME_L + 3},${DOME_Y}"/>
          <polyline class="curb" points="${DOME_R - 3},${ROOF_Y + 9} ${DOME_R - 3},${DOME_Y}"/>

          <!-- panneaux solaires -->
          <g class="pv">
            ${[206, 248, 290].map((x) => `
              <line class="leg" x1="${x + 34}" y1="${ROOF_Y}" x2="${x + 34}" y2="${ROOF_Y - 15}"/>
              <line class="leg" x1="${x + 6}" y1="${ROOF_Y}" x2="${x + 6}" y2="${ROOF_Y - 4}"/>
              <line class="panel" x1="${x}" y1="${ROOF_Y - 4}" x2="${x + 40}" y2="${ROOF_Y - 18}"/>`).join("")}
          </g>

          <!-- mât et station Ecowitt WS90 -->
          <g class="ws90" data-mi="outdoor_temp">
            <line class="mast" x1="358" y1="${ROOF_Y}" x2="358" y2="38"/>
            <rect x="348" y="28" width="20" height="12" rx="3" class="head"/>
            <path d="M346 28 Q358 16 370 28 Z" class="head"/>
          </g>

          <!-- vérin -->
          <line class="jack" x1="${DOME_R - 10}" y1="${ROOF_Y + 2}" x2="${jackTop.x.toFixed(1)}" y2="${jackTop.y.toFixed(1)}"/>

          <!-- coupole (charnière à gauche) -->
          <g class="dome ${isOpen ? "open" : ""} ${doorKnown ? "" : "unknown"} ${moving ? "moving" : ""}" transform="rotate(${-angle} ${DOME_L} ${DOME_Y})">
            <path d="M${DOME_L} ${DOME_Y} A${domeW / 2} ${DOME_H} 0 0 1 ${DOME_R} ${DOME_Y} Z"/>
            <line x1="${DOME_L - 2}" y1="${DOME_Y}" x2="${DOME_R + 2}" y2="${DOME_Y}" class="rim"/>
            <path d="M${DOME_L + 16} ${DOME_Y - 8} Q${DOME_L + 24} ${DOME_Y - DOME_H + 4} ${DOME_L + 40} ${DOME_Y - DOME_H + 2}" class="shine"/>
          </g>
          <circle cx="${DOME_L}" cy="${DOME_Y}" r="3.5" class="hinge"/>

          ${isOpen ? `<g class="air">
              <path d="M150 250 C150 190 150 130 170 98 S206 56 232 40"/>
              <path d="M176 246 C176 190 176 136 186 108 S216 74 244 62"/>
              <path d="M124 240 C126 190 132 132 154 100 S188 54 214 26"/>
            </g>` : ""}

          <!-- étiquettes -->
          <g class="lbl" data-mi="outdoor_temp">
            <rect x="244" y="4" width="98" height="76" rx="6"/>
            <text x="293" y="16" text-anchor="middle" class="cap">Extérieur</text>
            <text x="293" y="33" text-anchor="middle" class="big">${fmt(tOut, "°")}${hOut !== null ? `<tspan class="small"> · ${fmt(hOut, " %", 0)}</tspan>` : ""}</text>
            <text x="293" y="51" text-anchor="middle" class="small ${raining ? "alert" : ""}">Pluie ${rain === null ? "–" : `${rain.toFixed(1)} mm/h`}</text>
            <text x="293" y="67" text-anchor="middle" class="small ${windy ? "alert" : ""}">Rafales ${gust === null ? "–" : `${gust.toFixed(0)} ${esc(gustUnit)}`}</text>
          </g>

          <g class="lbl" data-mi="indoor_temp">
            <rect x="288" y="122" width="80" height="${hIn !== null ? 52 : 38}" rx="6"/>
            <text x="328" y="135" text-anchor="middle" class="cap">Cage d'escalier</text>
            <text x="328" y="152" text-anchor="middle" class="big">${fmt(tIn, "°")}</text>
            ${hIn !== null ? `<text x="328" y="167" text-anchor="middle" class="small">${fmt(hIn, " %", 0)}</text>` : ""}
          </g>

          <g class="lbl door" data-mi="door">
            <rect x="26" y="${ROOF_Y + 12}" width="${moving ? 118 : 92}" height="22" rx="11"/>
            <text x="${moving ? 85 : 72}" y="${ROOF_Y + 27}" text-anchor="middle" class="small b">${esc(doorText)}</text>
          </g>

          ${!isArmed ? `<g class="stamp"><rect x="230" y="222" width="140" height="26" rx="13"/><text x="300" y="240" text-anchor="middle">SYSTÈME DÉSARMÉ</text></g>` : ""}
        </svg>
        ${ovText || moving ? `<div class="chips">
          ${moving ? `<div class="chip warn" data-mi="door_tilt"><ha-icon icon="mdi:arrow-up-down"></ha-icon>En mouvement…</div>` : ""}
          ${ovText ? `<div class="chip prim" data-mi="override_end"><ha-icon icon="mdi:hand-back-right"></ha-icon>Manuel jusqu'à ${ovText}</div>` : ""}
        </div>` : ""}
        </div>
        ${this._config.show_pipeline ? `<div class="ladder">${ladder}</div>` : ""}
        </div>

        ${this._config.show_buttons ? `<div class="btns">
          <button class="open" data-act="open" ${manualOk ? "" : "disabled"} title="${esc(manualWhy)}"><ha-icon icon="mdi:arrow-up-bold"></ha-icon>Ouvrir</button>
          <button class="close" data-act="close" ${manualOk ? "" : "disabled"} title="${esc(manualWhy)}"><ha-icon icon="mdi:arrow-down-bold"></ha-icon>Fermer</button>
          <button class="auto" data-act="auto" ${ovText ? "" : "disabled"}><ha-icon icon="mdi:autorenew"></ha-icon>Auto</button>
        </div>` : ""}
      </ha-card>`;

    root.querySelectorAll("[data-mi]").forEach((el) =>
      el.addEventListener("click", () => this._moreInfo(el.dataset.mi))
    );
    const b = (sel, fn) => { const el = root.querySelector(sel); if (el) el.addEventListener("click", fn); };
    b('[data-act="open"]', () => this._press("open_button", "Ouvrir l'ouvrant ? La commande manuelle reste prioritaire pendant la durée réglée."));
    b('[data-act="close"]', () => this._press("close_button"));
    b('[data-act="auto"]', () => this._press("resume_button"));
  }
}

const STYLE = `
  :host { display:block; }
  ha-card { padding:12px 12px 14px; overflow:hidden; container-type:inline-size; }
  ha-card.alarm { animation: alarm 1s steps(2) infinite; }
  @keyframes alarm { 50% { box-shadow: 0 0 0 3px var(--error-color,#db4437) inset; } }
  .warn { padding:16px; color: var(--error-color,#db4437); }
  .head { display:flex; gap:12px; align-items:center; cursor:pointer; }
  .badge { width:40px; height:40px; border-radius:50%; display:flex; align-items:center; justify-content:center; color:#fff; flex:none; }
  .title { min-width:0; }
  .t1 { font-size:16px; font-weight:500; color:var(--primary-text-color); }
  .status { display:grid; grid-template-columns: 1fr 1fr; gap:8px; margin-top:10px; }
  .pill { display:flex; align-items:center; gap:10px; padding:8px 12px; border-radius:12px; cursor:pointer; color:#fff; background: var(--c); }
  .pill ha-icon { --mdc-icon-size:28px; flex:none; }
  .pill .pl { font-size:11px; opacity:.85; text-transform:uppercase; letter-spacing:.5px; }
  .pill .pv { font-size:18px; font-weight:600; line-height:1.15; }
  .pill .ps { font-size:11px; opacity:.85; }
  .body { display:grid; grid-template-columns: minmax(0, 1.9fr) minmax(150px, 1fr); gap:10px; align-items:start; margin-top:10px; }
  @container (max-width: 520px) { .body { grid-template-columns: 1fr; } }
  .main { min-width:0; }
  .scene { width:100%; height:auto; display:block; margin:0 0 6px; border-radius:12px; }
  .inside { fill: var(--secondary-background-color, #f2f2f2); }
  .roof { fill:none; stroke: var(--primary-text-color,#212121); stroke-width:10; stroke-linecap:butt; opacity:.8; }
  .wall { fill:none; stroke: var(--primary-text-color,#212121); stroke-width:10; opacity:.8; }
  .stairs { fill:none; stroke: var(--secondary-text-color,#727272); stroke-width:6; stroke-linejoin:round; opacity:.6; }
  .slab { fill:none; stroke: var(--primary-text-color,#212121); stroke-width:10; opacity:.55; }
  .pv .panel { stroke:#1f4e8c; stroke-width:6; stroke-linecap:round; }
  .pv .leg, .ws90 .mast { stroke: var(--secondary-text-color,#727272); stroke-width:3; }
  .ws90 { cursor:pointer; }
  .ws90 .head { fill: var(--card-background-color,#fff); stroke: var(--secondary-text-color,#727272); stroke-width:2; }
  .curb { fill:none; stroke: var(--primary-text-color,#212121); stroke-width:6; opacity:.8; }
  .dome path:first-child { fill: rgba(160,205,235,.45); stroke: var(--secondary-text-color,#727272); stroke-width:3; }
  .dome .rim { stroke: var(--secondary-text-color,#727272); stroke-width:6; stroke-linecap:round; }
  .dome .shine { fill:none; stroke:#fff; stroke-width:3; stroke-linecap:round; opacity:.7; }
  .dome.open path:first-child { stroke:#fb8c00; }
  .dome.open .rim { stroke:#fb8c00; }
  .dome.unknown path:first-child, .dome.unknown .rim { stroke-dasharray: 5 5; }
  .hinge { fill: var(--primary-text-color,#212121); }
  .jack { stroke: var(--secondary-text-color,#727272); stroke-width:4; stroke-linecap:round; }
  .air path { fill:none; stroke:#1e88e5; stroke-width:4; stroke-linecap:round; stroke-dasharray: 10 12; animation: flow 1.2s linear infinite; opacity:.85; }
  @keyframes flow { to { stroke-dashoffset:-22; } }
  .rain line { stroke:#4f8fd6; stroke-width:2.5; stroke-linecap:round; animation: fall .9s linear infinite; }
  @keyframes fall { from { transform: translateY(0); opacity:.9 } to { transform: translateY(150px); opacity:0 } }
  .wind path { fill:none; stroke: var(--secondary-text-color,#727272); stroke-width:3; stroke-linecap:round; stroke-dasharray: 30 200; animation: gust 1.6s linear infinite; }
  @keyframes gust { from { stroke-dashoffset: 120 } to { stroke-dashoffset: -120 } }
  .lbl { cursor:pointer; }
  .lbl rect { fill: var(--card-background-color,#fff); opacity:.92; stroke: var(--divider-color,#e0e0e0); }
  .lbl.door rect { fill: var(--card-background-color,#fff); }
  text { fill: var(--primary-text-color,#212121); font-family: var(--ha-font-family-body, Roboto, sans-serif); }
  text.big { font-size:16px; font-weight:600; }
  text.small, tspan.small { font-size:11.5px; font-weight:400; }
  text.alert { fill: var(--info-color,#039be5); font-weight:700; }
  .dome.moving path:first-child, .dome.moving .rim { animation: blink 1s ease-in-out infinite; }
  @keyframes blink { 50% { opacity:.4; } }
  text.b { font-weight:600; }
  text.cap { font-size:10px; fill: var(--secondary-text-color,#727272); }
  .stamp rect { fill: var(--error-color,#db4437); }
  .stamp text { fill:#fff; font-size:12px; font-weight:700; letter-spacing:1px; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; }
  .chip { display:flex; align-items:center; gap:4px; font-size:12px; padding:4px 10px 4px 6px; border-radius:16px; cursor:pointer;
          background: var(--secondary-background-color,#f2f2f2); color: var(--primary-text-color); }
  .chip ha-icon { --mdc-icon-size:16px; color: var(--secondary-text-color); }
  .chip.bad { background: var(--error-color,#db4437); color:#fff; } .chip.bad ha-icon { color:#fff; }
  .chip.info { background: var(--info-color,#039be5); color:#fff; } .chip.info ha-icon { color:#fff; }
  .chip.warn { background: var(--warning-color,#ffa600); color:#fff; } .chip.warn ha-icon { color:#fff; }
  .chip.prim { background: var(--primary-color,#03a9f4); color:#fff; } .chip.prim ha-icon { color:#fff; }
  .ladder { display:flex; flex-direction:column; gap:3px; }
  .lvl { display:flex; align-items:center; gap:8px; padding:3px 8px; border-radius:6px; font-size:12px; line-height:1.25;
         color: var(--secondary-text-color); background: var(--secondary-background-color,#f2f2f2); opacity:.6;
         border-left:4px solid transparent; }
  .lvl .p { font-weight:700; min-width:16px; text-align:right; }
  .lvl.on { opacity:1; border-left-color: var(--c); color: var(--primary-text-color); }
  .lvl.win { display:block; background: var(--c); color:#fff; opacity:1; padding:10px 12px; border-left:none; cursor:pointer; margin:3px 0; }
  .lvl.win .wh { display:flex; align-items:baseline; gap:8px; font-size:16px; font-weight:600; }
  .lvl.win .p { font-size:20px; }
  .lvl.win .r { font-size:13px; margin-top:4px; line-height:1.35; opacity:.95; }
  .btns { display:grid; grid-template-columns: 1fr 1fr 1fr; gap:8px; margin-top:12px; }
  button { display:flex; align-items:center; justify-content:center; gap:6px; border:none; border-radius:10px; padding:10px 6px;
           font-size:14px; font-weight:500; cursor:pointer; color:#fff; font-family: inherit; }
  button ha-icon { --mdc-icon-size:18px; }
  button.open { background:#fb8c00; } button.close { background: var(--info-color,#039be5); }
  button.auto { background: var(--secondary-background-color,#e0e0e0); color: var(--primary-text-color); }
  button:disabled { opacity:.35; cursor:not-allowed; }
`;

if (!customElements.get("ventilation-desenfumage-card")) {
  customElements.define("ventilation-desenfumage-card", VentilationDesenfumageCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "ventilation-desenfumage-card",
    name: "Ventilation désenfumage",
    description: "Vue graphique de l'ouvrant, de la météo et de la décision",
    preview: true,
  });
  console.info(`%c VENTILATION-DESENFUMAGE-CARD %c ${CARD_VERSION} `, "background:#fb8c00;color:#fff", "background:#455a64;color:#fff");
}
