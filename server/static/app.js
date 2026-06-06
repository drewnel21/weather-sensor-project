const grid = document.getElementById("grid");
const empty = document.getElementById("empty");
const conn = document.getElementById("conn");
const rangeToggle = document.getElementById("range-toggle");
const placeHint = document.getElementById("place-hint");

const cards = new Map();         // sensor_id -> { el, chart, series, sensor, marker }
const sensorColor = new Map();
let colorIdx = 0;
const PALETTE = ["#4cc2ff", "#fbbf24", "#4ade80", "#f87171", "#a78bfa", "#fb7185", "#34d399", "#fb923c"];

let currentRange = "24h";
let placingSensorId = null;

const RANGE_WINDOW_MS = { "24h": 24 * 3600e3, "7d": 7 * 86400e3, "30d": 30 * 86400e3 };

// Status thresholds (seconds). "Live" if we've seen a state message recently.
// "Stale" if the broker hasn't told us anything in a while — LWT should have
// fired by then, but in case the keepalive is generous or the broker missed
// it we degrade visually instead of pretending the sensor is healthy.
const STATUS_STALE_AFTER_S = 90;   // 3× the default 30s publish interval

function classifyStatus(sensor) {
  // online is true | false | null. null = never observed a status message
  // (e.g. sensor auto-registered from a state msg). Treat null as
  // "presumed online if last_seen is recent" — we don't want a brand-new
  // sensor to render as "offline" just because no retained status has
  // propagated yet.
  if (sensor.online === false) return "offline";
  const lastSeen = sensor.last_seen ?? sensor.last_reading?.ts ?? null;
  if (lastSeen == null) return "unknown";
  const ageS = Date.now() / 1000 - lastSeen;
  if (ageS > STATUS_STALE_AFTER_S) return "stale";
  return "live";
}

const STATUS_LABEL = {
  live: "live",
  stale: "stale",
  offline: "offline",
  unknown: "—",
};

const METRIC_META = {
  temperature_c: { convert: (c) => c == null ? null : c * 9 / 5 + 32, digits: 1 },
  humidity:      { convert: (v) => v,                                   digits: 1 },
  pressure_hpa:  { convert: (h) => h == null ? null : h * 0.02953,      digits: 2 },
};

function setConn(state, text) { conn.className = "conn conn-" + state; conn.textContent = text; }

function fmtRelative(tsSec) {
  if (tsSec == null) return "never";
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - tsSec));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
function fmtNum(v, digits) { return v == null ? "—" : Number(v).toFixed(digits); }

function colorFor(sensorId) {
  if (!sensorColor.has(sensorId)) {
    sensorColor.set(sensorId, PALETTE[colorIdx % PALETTE.length]);
    colorIdx++;
  }
  return sensorColor.get(sensorId);
}

// ---- Map ----------------------------------------------------------------
let map = null;
let mapReady = false;
const pendingUpserts = new Set(); // sensor_ids waiting for map to be ready

function popupHTML(sensor) {
  const r = sensor.last_reading;
  const tempF = METRIC_META.temperature_c.convert(r?.temperature_c);
  const presIn = METRIC_META.pressure_hpa.convert(r?.pressure_hpa);
  return `<b>${sensor.name || sensor.sensor_id}</b><br>`
    + (r
        ? `${fmtNum(tempF, 1)} °F · ${fmtNum(r.humidity, 1)} % · ${fmtNum(presIn, 2)} inHg<br>`
          + `<span style="color:var(--text-dim)">Updated ${fmtRelative(r.ts)}</span>`
        : `<span style="color:var(--text-dim)">no data yet</span>`);
}

function upsertMarker(entry) {
  if (!mapReady) { pendingUpserts.add(entry.sensor.sensor_id); return; }
  const s = entry.sensor;
  if (s.latitude == null || s.longitude == null) {
    if (entry.marker) { entry.marker.remove(); entry.marker = null; }
    return;
  }
  if (entry.marker) {
    entry.marker.setLngLat([s.longitude, s.latitude]);
    entry.marker.getPopup().setHTML(popupHTML(s));
  } else {
    const popup = new mapboxgl.Popup({ offset: 18, closeButton: false }).setHTML(popupHTML(s));
    entry.marker = new mapboxgl.Marker({ color: colorFor(s.sensor_id) })
      .setLngLat([s.longitude, s.latitude])
      .setPopup(popup)
      .addTo(map);
  }
}

function fitMapToMarkers() {
  if (!mapReady) return;
  const placed = [...cards.values()].filter(e => e.marker);
  if (placed.length === 0) return;
  if (placed.length === 1) {
    map.flyTo({ center: placed[0].marker.getLngLat(), zoom: 14, animate: false });
    return;
  }
  const bounds = new mapboxgl.LngLatBounds();
  for (const e of placed) bounds.extend(e.marker.getLngLat());
  map.fitBounds(bounds, { padding: 60, animate: false });
}

function enterPlacingMode(sensorId) {
  placingSensorId = sensorId;
  if (map) map.getContainer().classList.add("placing");
  placeHint.hidden = false;
  placeHint.textContent = `Click on the map to place ${sensorId}…`;
  for (const [id, entry] of cards) {
    const btn = entry.el.querySelector(".place-btn");
    btn.classList.toggle("placing", id === sensorId);
  }
}
function exitPlacingMode() {
  placingSensorId = null;
  if (map) map.getContainer().classList.remove("placing");
  placeHint.hidden = true;
  for (const entry of cards.values()) {
    entry.el.querySelector(".place-btn").classList.remove("placing");
  }
}

async function initMap() {
  let cfg;
  try {
    const r = await fetch("/api/config");
    cfg = await r.json();
  } catch (e) {
    console.error("Failed to load /api/config:", e);
    return;
  }
  if (!cfg.mapbox_token) {
    console.error("No Mapbox token configured. Set WEATHER_MAPBOX_TOKEN.");
    document.getElementById("map").textContent =
      "Map unavailable — server has no Mapbox token configured (set WEATHER_MAPBOX_TOKEN).";
    return;
  }
  mapboxgl.accessToken = cfg.mapbox_token;
  map = new mapboxgl.Map({
    container: "map",
    style: cfg.mapbox_style || "mapbox://styles/mapbox/streets-v12",
    center: [-98.35, 39.5],
    zoom: 3,
    attributionControl: false,
  });
  map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");

  map.on("click", async (ev) => {
    if (!placingSensorId) return;
    const sensorId = placingSensorId;
    const { lng, lat } = ev.lngLat;
    try {
      const r = await fetch(`/api/sensors/${encodeURIComponent(sensorId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ latitude: lat, longitude: lng }),
      });
      if (!r.ok) throw new Error(await r.text());
      const entry = cards.get(sensorId);
      entry.sensor.latitude = lat;
      entry.sensor.longitude = lng;
      upsertMarker(entry);
      updatePlaceButton(entry);
    } catch (e) {
      console.error("Failed to place sensor:", e);
    }
    exitPlacingMode();
  });

  map.on("load", () => {
    mapReady = true;
    for (const id of pendingUpserts) {
      const entry = cards.get(id);
      if (entry) upsertMarker(entry);
    }
    pendingUpserts.clear();
    fitMapToMarkers();
  });
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && placingSensorId) exitPlacingMode();
});

// ---- Card chart ---------------------------------------------------------
function makeCardChart(canvas) {
  return new Chart(canvas, {
    type: "line",
    data: { datasets: [
      { label: "°F",   yAxisID: "y_t", borderColor: "#4cc2ff", backgroundColor: "rgba(76,194,255,0.1)", borderWidth: 1.5, pointRadius: 0, tension: 0.25, data: [] },
      { label: "%",    yAxisID: "y_h", borderColor: "#4ade80", backgroundColor: "rgba(74,222,128,0.1)", borderWidth: 1.5, pointRadius: 0, tension: 0.25, data: [] },
      { label: "inHg", yAxisID: "y_p", borderColor: "#fbbf24", backgroundColor: "rgba(251,191,36,0.1)", borderWidth: 1.5, pointRadius: 0, tension: 0.25, data: [] },
    ]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false } },
      scales: {
        x: { type: "time", ticks: { color: "#8a909c", maxTicksLimit: 5 }, grid: { color: "rgba(255,255,255,0.04)" } },
        y_t: { position: "left",  ticks: { color: "#4cc2ff", font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.04)" } },
        y_h: { position: "right", ticks: { color: "#4ade80", font: { size: 10 } }, grid: { display: false } },
        y_p: { position: "right", ticks: { color: "#fbbf24", font: { size: 10 } }, grid: { display: false }, offset: true },
      },
    },
  });
}

function pointsToSeries(points) {
  return {
    temperature_c: points.map(p => ({ x: p.ts * 1000, y: METRIC_META.temperature_c.convert(p.temperature_c) })),
    humidity:      points.map(p => ({ x: p.ts * 1000, y: p.humidity })),
    pressure_hpa:  points.map(p => ({ x: p.ts * 1000, y: METRIC_META.pressure_hpa.convert(p.pressure_hpa) })),
  };
}
function applySeriesToCardChart(chart, series) {
  chart.data.datasets[0].data = series.temperature_c;
  chart.data.datasets[1].data = series.humidity;
  chart.data.datasets[2].data = series.pressure_hpa;
  chart.update("none");
}

// ---- Cards --------------------------------------------------------------
function updatePlaceButton(entry) {
  const btn = entry.el.querySelector(".place-btn");
  const placed = entry.sensor.latitude != null && entry.sensor.longitude != null;
  btn.textContent = placed ? "📍 Move on map" : "📍 Place on map";
}

function renderCard(sensor) {
  const id = sensor.sensor_id;
  let entry = cards.get(id);
  const r = sensor.last_reading;
  if (!entry) {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `
      <div class="card-header">
        <div class="card-id-block">
          <a class="card-link" href="/sensor/${encodeURIComponent(id)}">
            <span class="status-pill status-unknown"><span class="status-dot"></span><span class="status-label">—</span></span>
            <span class="card-name"></span>
          </a>
          <div class="card-id"></div>
        </div>
        <div class="card-actions">
          <button class="rename-btn" title="Rename" aria-label="Rename sensor">✏️</button>
          <button class="place-btn">📍 Place on map</button>
          <button class="delete-btn" title="Delete sensor" aria-label="Delete sensor">🗑️</button>
        </div>
      </div>
      <div class="metrics">
        <div class="metric"><span class="metric-label">Temp</span>
          <span><span class="metric-value temp">—</span><span class="metric-unit">°F</span></span></div>
        <div class="metric"><span class="metric-label">Humidity</span>
          <span><span class="metric-value hum">—</span><span class="metric-unit">%</span></span></div>
        <div class="metric"><span class="metric-label">Pressure</span>
          <span><span class="metric-value pres">—</span><span class="metric-unit">inHg</span></span></div>
      </div>
      <div class="chart-wrap"><canvas></canvas></div>
      <div class="card-footer"><span class="seen">no data yet</span></div>
    `;
    grid.appendChild(el);
    const chart = makeCardChart(el.querySelector("canvas"));
    entry = { el, chart, series: null, sensor: { ...sensor }, marker: null };
    cards.set(id, entry);
    colorFor(id);
    el.querySelector(".place-btn").addEventListener("click", () => {
      if (placingSensorId === id) exitPlacingMode();
      else enterPlacingMode(id);
    });
    el.querySelector(".rename-btn").addEventListener("click", () => startRenaming(entry));
    el.querySelector(".delete-btn").addEventListener("click", () => confirmDelete(entry));
  } else {
    entry.sensor = { ...entry.sensor, ...sensor };
  }
  // If the name is currently being edited (input element in place of the
  // span), don't clobber what the user is typing. The edit handler will
  // restore the .card-name span when it finishes.
  const nameEl = entry.el.querySelector(".card-name");
  if (nameEl) nameEl.textContent = sensor.name || id;
  entry.el.querySelector(".card-id").textContent = id;
  entry.el.querySelector(".temp").textContent = fmtNum(METRIC_META.temperature_c.convert(r?.temperature_c), 1);
  entry.el.querySelector(".hum").textContent  = fmtNum(r?.humidity, 1);
  entry.el.querySelector(".pres").textContent = fmtNum(METRIC_META.pressure_hpa.convert(r?.pressure_hpa), 2);
  const seenEl = entry.el.querySelector(".seen");
  seenEl.dataset.ts = r?.ts ?? "";
  seenEl.textContent = r ? `Updated ${fmtRelative(r.ts)}` : "no data yet";
  updatePlaceButton(entry);
  renderStatus(entry);
  upsertMarker(entry);
  updateEmptyState();
}

function startRenaming(entry) {
  // Idempotent — clicking the button while already editing is a no-op rather
  // than spawning a second input.
  if (entry.editing) return;
  const nameEl = entry.el.querySelector(".card-name");
  if (!nameEl) return;

  const currentName = entry.sensor.name || entry.sensor.sensor_id;
  entry.editing = true;

  const input = document.createElement("input");
  input.className = "card-name-input";
  input.type = "text";
  input.value = currentName;
  input.maxLength = 80;
  input.spellcheck = false;
  // Replace the span in place so the surrounding layout doesn't shift.
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  let settled = false;
  const finish = async (commit) => {
    if (settled) return;  // blur fires after Enter; ignore the second call
    settled = true;
    const proposed = input.value.trim();
    let finalName = currentName;
    if (commit && proposed && proposed !== currentName) {
      try {
        const r = await fetch(
          `/api/sensors/${encodeURIComponent(entry.sensor.sensor_id)}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: proposed }),
          }
        );
        if (!r.ok) throw new Error(await r.text());
        entry.sensor.name = proposed;
        finalName = proposed;
        // Marker popup also displays the name — refresh so it doesn't lag.
        if (entry.marker) entry.marker.getPopup().setHTML(popupHTML(entry.sensor));
      } catch (e) {
        console.error("Rename failed:", e);
        finalName = currentName;  // revert visually on failure
      }
    }
    const span = document.createElement("span");
    span.className = "card-name";
    span.textContent = finalName;
    input.replaceWith(span);
    entry.editing = false;
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}

async function confirmDelete(entry) {
  const id = entry.sensor.sensor_id;
  const label = entry.sensor.name || id;
  // Native confirm is fine here — deletion is destructive and rare, and a
  // blocking prompt is exactly the friction we want.
  if (!window.confirm(`Delete "${label}" and all of its history?\n\nThis cannot be undone.`)) return;
  try {
    const r = await fetch(`/api/sensors/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
    // The server also broadcasts a "deleted" event; removeCardById is
    // idempotent so the echo on our own socket is harmless.
    removeCardById(id);
  } catch (e) {
    console.error("Delete failed:", e);
    alert(`Could not delete ${label}: ${e.message}`);
  }
}

function removeCardById(id) {
  const entry = cards.get(id);
  if (!entry) return;
  if (entry.marker) { entry.marker.remove(); entry.marker = null; }
  if (entry.chart) entry.chart.destroy();
  entry.el.remove();
  cards.delete(id);
  if (placingSensorId === id) exitPlacingMode();
  updateEmptyState();
}

function renderStatus(entry) {
  const status = classifyStatus(entry.sensor);
  const pill = entry.el.querySelector(".status-pill");
  pill.className = `status-pill status-${status}`;
  pill.querySelector(".status-label").textContent = STATUS_LABEL[status];
  // Card border reflects offline state for at-a-glance scanning.
  entry.el.classList.toggle("card-offline", status === "offline");
  entry.el.classList.toggle("card-stale", status === "stale");
}

function flashCard(id) {
  const entry = cards.get(id);
  if (!entry) return;
  entry.el.classList.remove("flash");
  void entry.el.offsetWidth;
  entry.el.classList.add("flash");
}

function updateEmptyState() { empty.hidden = cards.size > 0; }

function trimSeries(series, windowMs) {
  const cutoff = Date.now() - windowMs;
  for (const key of Object.keys(series)) series[key] = series[key].filter(p => p.x >= cutoff);
}

function applyReading(ev) {
  const xy = pointsToSeries([{
    ts: ev.ts, temperature_c: ev.temperature_c, humidity: ev.humidity, pressure_hpa: ev.pressure_hpa,
  }]);
  const existing = cards.get(ev.sensor_id);
  // A reading implies the sensor is reachable right now. We don't override
  // online=false (the LWT is the source of truth there), but we do bump
  // last_seen so classifyStatus sees the sensor as live. Crucially, last_seen
  // is the EVENT ARRIVAL time, not ev.ts: a sensor whose clock is wrong (e.g.
  // NTP failed → year-2000 timestamps) is still alive when its reading lands,
  // and liveness must reflect "when we last heard from it," not what time the
  // device thinks it is.
  const nowSec = Math.floor(Date.now() / 1000);
  const lastReading = { ts: ev.ts, temperature_c: ev.temperature_c, humidity: ev.humidity, pressure_hpa: ev.pressure_hpa, rssi: ev.rssi };
  const sensor = existing
    ? { ...existing.sensor, last_reading: lastReading, last_seen: nowSec }
    : { sensor_id: ev.sensor_id, name: ev.sensor_id, latitude: null, longitude: null,
        online: null, last_seen: nowSec, last_reading: lastReading };
  renderCard(sensor);
  const entry = cards.get(ev.sensor_id);
  if (entry.series == null) entry.series = { temperature_c: [], humidity: [], pressure_hpa: [] };
  entry.series.temperature_c.push(xy.temperature_c[0]);
  entry.series.humidity.push(xy.humidity[0]);
  entry.series.pressure_hpa.push(xy.pressure_hpa[0]);
  trimSeries(entry.series, RANGE_WINDOW_MS[currentRange]);
  applySeriesToCardChart(entry.chart, entry.series);
  flashCard(ev.sensor_id);
}

function applyStatus(ev) {
  // Status events can arrive for unknown sensor_ids too (broker's retained
  // LWT for a sensor that hasn't published a reading yet). Render a minimal
  // card in that case so the user sees the offline indicator immediately.
  const existing = cards.get(ev.sensor_id);
  const sensor = existing
    ? { ...existing.sensor, online: ev.online, last_seen: ev.ts }
    : { sensor_id: ev.sensor_id, name: ev.sensor_id, latitude: null, longitude: null,
        online: ev.online, last_seen: ev.ts, last_reading: null };
  renderCard(sensor);
}

async function loadSensors() {
  const r = await fetch("/api/sensors");
  const list = await r.json();
  for (const s of list) renderCard(s);
  updateEmptyState();
  fitMapToMarkers();
  await Promise.all(list.map(s => loadHistory(s.sensor_id)));
}

async function loadHistory(sensorId) {
  try {
    const r = await fetch(`/api/sensors/${encodeURIComponent(sensorId)}/readings?range=${currentRange}`);
    const data = await r.json();
    const entry = cards.get(sensorId);
    if (!entry) return;
    entry.series = pointsToSeries(data.points);
    applySeriesToCardChart(entry.chart, entry.series);
  } catch (e) {
    console.error(`Failed to load history for ${sensorId}:`, e);
  }
}
async function reloadAllHistory() {
  await Promise.all([...cards.keys()].map(loadHistory));
}

function refreshTimes() {
  for (const entry of cards.values()) {
    const seenEl = entry.el.querySelector(".seen");
    const ts = Number(seenEl.dataset.ts);
    if (ts) seenEl.textContent = `Updated ${fmtRelative(ts)}`;
    // Re-classify status on every tick so live→stale rolls over without
    // waiting for another event. classifyStatus is cheap.
    renderStatus(entry);
  }
}

function setActive(group, btn) {
  for (const b of group.querySelectorAll("button")) b.classList.remove("active");
  btn.classList.add("active");
}

rangeToggle.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-range]");
  if (!btn) return;
  currentRange = btn.dataset.range;
  setActive(rangeToggle, btn);
  reloadAllHistory();
});

function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onopen = () => setConn("ok", "live");
  ws.onclose = () => {
    setConn("err", "disconnected — retrying");
    setTimeout(connectWS, 2000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "reading") applyReading(ev);
    else if (ev.type === "status") applyStatus(ev);
    else if (ev.type === "deleted") removeCardById(ev.sensor_id);
  };
}

initMap();
loadSensors();
connectWS();
setInterval(refreshTimes, 5000);
