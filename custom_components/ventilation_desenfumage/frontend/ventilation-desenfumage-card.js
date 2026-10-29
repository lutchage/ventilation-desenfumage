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

const CARD_VERSION = "0.3.1";

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
  alarme: "Alarme", desarme: "Désarmé", coupure: "Coupure", maintenance: "Maint.", defaut: "Défaut",
  station: "Station", meteo: "Météo", manuel: "Manuel", ventilation: "Ventil.", defaut_ferme: "Fermé",
};

const SEASON_LABEL = { froid: "Froid", normal: "Normal", canicule: "Canicule" };
const SEASON_ICON = { froid: "mdi:snowflake", normal: "mdi:weather-partly-cloudy", canicule: "mdi:white-balance-sunny" };

// Géométrie de la scène (viewBox 400 x 240) : toit plat, coupole sur costière
const ROOF_Y = 136; // dessus de la dalle
const DOME_L = 172; // bord gauche de la costière
const DOME_R = 248; // bord droit = charnière de la coupole
const DOME_Y = 116; // haut de la costière (appui de la coupole)
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
    if (isOpen) angle = tilt !== null ? Math.max(25, Math.min(90, tilt)) : 45;
    const doorText = !doorKnown ? "État inconnu" : isOpen ? (tilt !== null ? `Ouvert ${Math.round(tilt)}°` : "Ouvert") : "Fermé";

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

    // --- Coupole : rotation autour de la charnière droite, le côté gauche se soulève
    const rad = (angle * Math.PI) / 180;
    const arm = 0.55 * (DOME_R - DOME_L); // point d'attache du vérin sur le cadre
    const jackTop = { x: DOME_R - arm * Math.cos(rad), y: DOME_Y - arm * Math.sin(rad) };
    const domeW = DOME_R - DOME_L;

    const pipeline = trace
      .map((t) => {
        const win = t.key === key;
        const c = LEVEL_COLORS[t.key] || LEVEL_COLORS.defaut_ferme;
        return `<div class="lvl ${t.active ? "on" : ""} ${win ? "win" : ""}" style="--c:${c}" title="${esc(t.priority + " – " + t.label + (t.reason ? " : " + t.reason : ""))}">
          <span class="p">${t.priority}</span><span class="n">${esc(SHORT_LABEL[t.key] || t.label)}</span></div>`;
      })
      .join("");

    root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card class="${alarm ? "alarm" : ""}">
        <div class="head" data-mi="__decision">
          <div class="badge" style="background:${color}"><ha-icon icon="${isOpen ? "mdi:window-open-variant" : "mdi:window-closed-variant"}"></ha-icon></div>
          <div class="title">
            <div class="t1">${esc(this._config.title || "Ouvrant cage d'escalier")}</div>
            <div class="t2"><b style="color:${color}">${esc(dec.state)}</b> · ${esc(a.raison || "")}</div>
          </div>
        </div>

        <svg class="scene" viewBox="0 0 400 240" role="img" aria-label="${esc(doorText)}">
          <defs>
            <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="${night ? "#1b2440" : "#9fd3f5"}"/>
              <stop offset="1" stop-color="${night ? "#2e3b63" : "#dff1fc"}"/>
            </linearGradient>
            <clipPath id="inside"><rect x="56" y="146" width="288" height="94"/></clipPath>
          </defs>

          <rect x="0" y="0" width="400" height="240" fill="url(#sky)" opacity="0.55"/>
          ${night
            ? `<circle cx="352" cy="34" r="13" fill="#f4f1d0"/><circle cx="358" cy="29" r="12" fill="#2a3659" opacity="0.9"/>`
            : `<circle cx="352" cy="34" r="14" fill="#ffc94a"/>`}

          ${windy ? `<g class="wind">
              <path d="M84 22 Q130 12 176 22" /><path d="M96 44 Q140 34 184 44" /><path d="M0 84 Q36 76 72 84" />
            </g>` : ""}

          ${raining ? `<g class="rain">${[20, 60, 100, 140, 300, 340, 380, 170, 240].map((x, i) =>
            `<line x1="${x}" y1="${-10 - (i % 3) * 25}" x2="${x - 6}" y2="${4 - (i % 3) * 25}" style="animation-delay:${(i * 0.17).toFixed(2)}s"/>`).join("")}</g>` : ""}

          <!-- intérieur (dernier étage) -->
          <rect x="50" y="146" width="300" height="94" class="inside"/>
          <g clip-path="url(#inside)">
            <polyline class="stairs" points="66,240 66,218 100,218 100,194 134,194 134,170 ${DOME_L + 4},170 ${DOME_L + 4},150"/>
          </g>

          <!-- dalle (trémie sous la coupole), acrotères et murs -->
          <polyline class="roof" points="40,${ROOF_Y + 5} ${DOME_L},${ROOF_Y + 5}"/>
          <polyline class="roof" points="${DOME_R},${ROOF_Y + 5} 360,${ROOF_Y + 5}"/>
          <polyline class="wall" points="44,${ROOF_Y - 12} 44,240"/>
          <polyline class="wall" points="356,${ROOF_Y - 12} 356,240"/>
          <!-- costière -->
          <polyline class="curb" points="${DOME_L + 3},${ROOF_Y + 9} ${DOME_L + 3},${DOME_Y}"/>
          <polyline class="curb" points="${DOME_R - 3},${ROOF_Y + 9} ${DOME_R - 3},${DOME_Y}"/>

          <!-- vérin -->
          <line class="jack" x1="${DOME_L + 10}" y1="${ROOF_Y + 2}" x2="${jackTop.x.toFixed(1)}" y2="${jackTop.y.toFixed(1)}"/>

          <!-- coupole -->
          <g class="dome ${isOpen ? "open" : ""} ${doorKnown ? "" : "unknown"}" transform="rotate(${angle} ${DOME_R} ${DOME_Y})">
            <path d="M${DOME_L} ${DOME_Y} A${domeW / 2} ${DOME_H} 0 0 1 ${DOME_R} ${DOME_Y} Z"/>
            <line x1="${DOME_L - 2}" y1="${DOME_Y}" x2="${DOME_R + 2}" y2="${DOME_Y}" class="rim"/>
            <path d="M${DOME_L + 16} ${DOME_Y - 8} Q${DOME_L + 24} ${DOME_Y - DOME_H + 4} ${DOME_L + 40} ${DOME_Y - DOME_H + 2}" class="shine"/>
          </g>
          <circle cx="${DOME_R}" cy="${DOME_Y}" r="3.5" class="hinge"/>

          ${isOpen ? `<g class="air">
              <path d="M196 214 C196 170 196 140 170 40"/>
              <path d="M218 220 C218 176 214 146 196 54"/>
              <path d="M176 206 C176 170 172 140 146 66"/>
            </g>` : ""}

          <!-- étiquettes -->
          <g class="lbl" data-mi="outdoor_temp">
            <rect x="8" y="8" width="64" height="${hOut !== null ? 52 : 38}" rx="6"/>
            <text x="40" y="21" text-anchor="middle" class="cap">Extérieur</text>
            <text x="40" y="38" text-anchor="middle" class="big">${fmt(tOut, "°")}</text>
            ${hOut !== null ? `<text x="40" y="53" text-anchor="middle" class="small">${fmt(hOut, " %", 0)}</text>` : ""}
          </g>

          <g class="lbl" data-mi="indoor_temp">
            <rect x="262" y="164" width="80" height="${hIn !== null ? 52 : 38}" rx="6"/>
            <text x="302" y="177" text-anchor="middle" class="cap">Cage d'escalier</text>
            <text x="302" y="194" text-anchor="middle" class="big">${fmt(tIn, "°")}</text>
            ${hIn !== null ? `<text x="302" y="209" text-anchor="middle" class="small">${fmt(hIn, " %", 0)}</text>` : ""}
          </g>

          <g class="lbl door" data-mi="door">
            <rect x="262" y="88" width="88" height="22" rx="11"/>
            <text x="306" y="103" text-anchor="middle" class="small b">${esc(doorText)}</text>
          </g>

          ${!isArmed ? `<g class="stamp"><rect x="110" y="6" width="180" height="26" rx="13"/><text x="200" y="24" text-anchor="middle">SYSTÈME DÉSARMÉ</text></g>` : ""}
        </svg>

        <div class="chips">
          <div class="chip" data-mi="season"><ha-icon icon="${SEASON_ICON[seasonVal] || "mdi:calendar"}"></ha-icon>
            ${esc(SEASON_LABEL[seasonVal] || "–")}${avg !== null ? ` · moy. ${avg.toFixed(1)}°` : ""}</div>
          <div class="chip ${isArmed ? "" : "bad"}" data-mi="armed_switch"><ha-icon icon="${isArmed ? "mdi:shield-check" : "mdi:shield-off"}"></ha-icon>${isArmed ? "Armé" : "Désarmé"}</div>
          <div class="chip ${raining ? "info" : ""}" data-mi="rain_rate"><ha-icon icon="mdi:weather-rainy"></ha-icon>${rain === null ? "–" : `${rain.toFixed(1)} mm/h`}</div>
          <div class="chip ${windy ? "info" : ""}" data-mi="wind_gust"><ha-icon icon="mdi:weather-windy"></ha-icon>${gust === null ? "–" : `${gust.toFixed(0)} ${esc(gustUnit)}`}</div>
          ${ovText ? `<div class="chip prim" data-mi="override_end"><ha-icon icon="mdi:hand-back-right"></ha-icon>Manuel jusqu'à ${ovText}</div>` : ""}
        </div>

        ${this._config.show_pipeline ? `<div class="pipe">${pipeline}</div>` : ""}

        ${this._config.show_buttons ? `<div class="btns">
          <button class="open" data-act="open" ${isArmed ? "" : "disabled"}><ha-icon icon="mdi:arrow-up-bold"></ha-icon>Ouvrir</button>
          <button class="close" data-act="close" ${isArmed ? "" : "disabled"}><ha-icon icon="mdi:arrow-down-bold"></ha-icon>Fermer</button>
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
  ha-card { padding:12px 12px 14px; overflow:hidden; }
  ha-card.alarm { animation: alarm 1s steps(2) infinite; }
  @keyframes alarm { 50% { box-shadow: 0 0 0 3px var(--error-color,#db4437) inset; } }
  .warn { padding:16px; color: var(--error-color,#db4437); }
  .head { display:flex; gap:12px; align-items:center; cursor:pointer; }
  .badge { width:40px; height:40px; border-radius:50%; display:flex; align-items:center; justify-content:center; color:#fff; flex:none; }
  .title { min-width:0; }
  .t1 { font-size:16px; font-weight:500; color:var(--primary-text-color); }
  .t2 { font-size:13px; color:var(--secondary-text-color); line-height:1.35; }
  .scene { width:100%; height:auto; display:block; margin:10px 0 6px; border-radius:12px; }
  .inside { fill: var(--secondary-background-color, #f2f2f2); }
  .roof { fill:none; stroke: var(--primary-text-color,#212121); stroke-width:10; stroke-linecap:butt; opacity:.8; }
  .wall { fill:none; stroke: var(--primary-text-color,#212121); stroke-width:10; opacity:.8; }
  .stairs { fill:none; stroke: var(--secondary-text-color,#727272); stroke-width:6; stroke-linejoin:round; opacity:.6; }
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
  text.big { font-size:15px; font-weight:600; }
  text.small { font-size:11px; }
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
  .chip.prim { background: var(--primary-color,#03a9f4); color:#fff; } .chip.prim ha-icon { color:#fff; }
  .pipe { display:grid; grid-template-columns: repeat(10, 1fr); gap:3px; margin-top:12px; }
  .lvl { display:flex; flex-direction:column; align-items:center; gap:2px; padding:5px 1px 4px; border-radius:6px;
         background: var(--secondary-background-color,#f2f2f2); opacity:.55; min-width:0; }
  .lvl .p { font-size:12px; font-weight:700; color: var(--secondary-text-color); }
  .lvl .n { font-size:10px; line-height:1.1; text-align:center; color: var(--secondary-text-color);
            overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
  .lvl.on { opacity:1; box-shadow: inset 0 -3px 0 var(--c); }
  .lvl.win { background: var(--c); opacity:1; box-shadow:none; }
  .lvl.win .p, .lvl.win .n { color:#fff; }
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
