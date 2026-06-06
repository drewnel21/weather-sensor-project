// Detail page — single sensor, three large per-metric charts, summary stats.

const sensorId = decodeURIComponent(location.pathname.replace(/^\/sensor\//, ""));
document.title = `${sensorId} — Weather Sensor Stations`;
document.getElementById("sensor-title").textContent = sensorId;
document.getElementById("sensor-id-line").textContent = sensorId;

const conn = document.getElementById("conn");
const rangeToggle = document.getElementById("range-toggle");

let currentRange = "24h";
const RANGE_WINDOW_MS = { "24h": 24 * 3600e3, "7d": 7 * 86400e3, "30d": 30 * 86400e3 };

// Local copy of this sensor's status state. Mirrored from /api/sensors at
// load time and updated by WS status events. Used by renderStatus() to keep
// the badge in sync between renders.
const sensorState = { online: null, last_seen: null };

const STATUS_STALE_AFTER_S = 90;
const STATUS_LABEL = { live: "live", stale: "stale", offline: "offline", unknown: "—" };

function classifyStatus(state) {
  if (state.online === false) return "offline";
  if (state.last_seen == null) return "unknown";
  const ageS = Date.now() / 1000 - state.last_seen;
  if (ageS > STATUS_STALE_AFTER_S) return "stale";
  return "live";
}

function renderStatus() {
  const status = classifyStatus(sensorState);
  const pill = document.getElementById("sensor-status");
  if (!pill) return;
  pill.className = `status-pill status-${status}`;
  pill.querySelector(".status-label").textContent = STATUS_LABEL[status];
}

const METRIC_META = {
  temperature_c: { convert: (c) => c == null ? null : c * 9 / 5 + 32, digits: 1, unit: "°F" },
  humidity:      { convert: (v) => v,                                  digits: 1, unit: "%" },
  pressure_hpa:  { convert: (h) => h == null ? null : h * 0.02953,     digits: 2, unit: "inHg" },
};

function setConn(state, text) { conn.className = "conn conn-" + state; conn.textContent = text; }
function fmtNum(v, d) { return v == null ? "—" : Number(v).toFixed(d); }
function fmtRelative(tsSec) {
  if (tsSec == null) return "never";
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - tsSec));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function makeChart(canvas, color, unit) {
  return new Chart(canvas, {
    type: "line",
    data: { datasets: [{
      label: unit,
      borderColor: color,
      backgroundColor: color + "1f",
      borderWidth: 1.8,
      pointRadius: 0,
      tension: 0.25,
      fill: true,
      data: [],
    }]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { mode: "index", intersect: false },
      },
      scales: {
        x: { type: "time", ticks: { color: "#8a909c" }, grid: { color: "rgba(255,255,255,0.04)" } },
        y: { ticks: { color: "#8a909c" }, grid: { color: "rgba(255,255,255,0.04)" } },
      },
    },
  });
}

const charts = {
  temperature_c: makeChart(document.getElementById("chart-temp"), "#4cc2ff", "°F"),
  humidity:      makeChart(document.getElementById("chart-hum"),  "#4ade80", "%"),
  pressure_hpa:  makeChart(document.getElementById("chart-pres"), "#fbbf24", "inHg"),
};

const series = { temperature_c: [], humidity: [], pressure_hpa: [] };

function applySeriesToCharts() {
  charts.temperature_c.data.datasets[0].data = series.temperature_c;
  charts.humidity.data.datasets[0].data      = series.humidity;
  charts.pressure_hpa.data.datasets[0].data  = series.pressure_hpa;
  for (const c of Object.values(charts)) c.update("none");
}

function pointsToSeries(points) {
  series.temperature_c = points.map(p => ({ x: p.ts * 1000, y: METRIC_META.temperature_c.convert(p.temperature_c) }));
  series.humidity      = points.map(p => ({ x: p.ts * 1000, y: p.humidity }));
  series.pressure_hpa  = points.map(p => ({ x: p.ts * 1000, y: METRIC_META.pressure_hpa.convert(p.pressure_hpa) }));
}

function renderSummary(summary) {
  const setOne = (id, m, key) => {
    const el = document.getElementById(id);
    if (!summary || summary.count === 0 || !summary[key]) {
      el.textContent = "no data";
      return;
    }
    const meta = METRIC_META[key];
    const conv = meta.convert;
    const s = summary[key];
    el.innerHTML =
      `<span class="lo">${fmtNum(conv(s.min), meta.digits)}</span>` +
      ` / <span class="avg">avg ${fmtNum(conv(s.avg), meta.digits)}</span>` +
      ` / <span class="hi">${fmtNum(conv(s.max), meta.digits)}</span> ${meta.unit}`;
  };
  setOne("sum-temp",  "temperature_c", "temperature_c");
  setOne("sum-hum",   "humidity",      "humidity");
  setOne("sum-pres",  "pressure_hpa",  "pressure_hpa");
}

function renderCurrent(reading) {
  document.getElementById("cur-temp").textContent =
    fmtNum(METRIC_META.temperature_c.convert(reading?.temperature_c), 1);
  document.getElementById("cur-hum").textContent  = fmtNum(reading?.humidity, 1);
  document.getElementById("cur-pres").textContent =
    fmtNum(METRIC_META.pressure_hpa.convert(reading?.pressure_hpa), 2);
  document.getElementById("last-seen").textContent =
    reading ? `Updated ${fmtRelative(reading.ts)}` : "no data yet";
  document.getElementById("last-seen").dataset.ts = reading?.ts ?? "";
}

async function loadSensorMeta() {
  // Seed sensorState from /api/sensors so the badge isn't "unknown" on first
  // paint. We pull the whole list and filter, which is fine for the small
  // sensor counts this project targets.
  try {
    const r = await fetch("/api/sensors");
    if (!r.ok) return;
    const list = await r.json();
    const me = list.find(s => s.sensor_id === sensorId);
    if (me) {
      sensorState.online = me.online;
      sensorState.last_seen = me.last_seen ?? me.last_reading?.ts ?? null;
      renderStatus();
      // If the sensor has been renamed, show the friendly name in the title
      // and keep the immutable sensor_id in the footer line below the metrics
      // (which sensor.html already wires up via #sensor-id-line).
      if (me.name && me.name !== sensorId) {
        document.getElementById("sensor-title").textContent = me.name;
        document.title = `${me.name} — Weather Sensor Stations`;
      }
    }
  } catch (e) {
    console.error("Failed to load sensor metadata:", e);
  }
}

async function loadHistory() {
  try {
    const r = await fetch(`/api/sensors/${encodeURIComponent(sensorId)}/readings?range=${currentRange}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    pointsToSeries(data.points);
    applySeriesToCharts();
    renderSummary(data.summary);
    if (data.points.length > 0) {
      const last = data.points[data.points.length - 1];
      renderCurrent({
        ts: last.ts,
        temperature_c: last.temperature_c,
        humidity: last.humidity,
        pressure_hpa: last.pressure_hpa,
      });
    } else {
      renderCurrent(null);
    }
  } catch (e) {
    console.error("Failed to load history:", e);
  }
}

function trimSeries(windowMs) {
  const cutoff = Date.now() - windowMs;
  for (const key of Object.keys(series)) series[key] = series[key].filter(p => p.x >= cutoff);
}

function applyReading(ev) {
  if (ev.sensor_id !== sensorId) return;
  const x = ev.ts * 1000;
  series.temperature_c.push({ x, y: METRIC_META.temperature_c.convert(ev.temperature_c) });
  series.humidity.push({ x, y: ev.humidity });
  series.pressure_hpa.push({ x, y: METRIC_META.pressure_hpa.convert(ev.pressure_hpa) });
  trimSeries(RANGE_WINDOW_MS[currentRange]);
  applySeriesToCharts();
  renderCurrent({
    ts: ev.ts,
    temperature_c: ev.temperature_c,
    humidity: ev.humidity,
    pressure_hpa: ev.pressure_hpa,
  });
  // A reading implies the sensor is reachable. Bump last_seen for stale-timer
  // purposes using EVENT ARRIVAL time, not ev.ts — a sensor with a wrong clock
  // (NTP failed → year-2000 timestamps) is still alive when its reading lands.
  // Don't override online=false (LWT is the source of truth).
  sensorState.last_seen = Math.floor(Date.now() / 1000);
  renderStatus();
  // Summary intentionally not recomputed client-side — relies on the next range
  // change or reload to refresh it from the server.
}

function applyStatus(ev) {
  if (ev.sensor_id !== sensorId) return;
  sensorState.online = ev.online;
  sensorState.last_seen = ev.ts;
  renderStatus();
}

function refreshTimes() {
  const el = document.getElementById("last-seen");
  const ts = Number(el.dataset.ts);
  if (ts) el.textContent = `Updated ${fmtRelative(ts)}`;
  // Roll live → stale automatically as time passes.
  renderStatus();
}

rangeToggle.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-range]");
  if (!btn) return;
  for (const b of rangeToggle.querySelectorAll("button")) b.classList.remove("active");
  btn.classList.add("active");
  currentRange = btn.dataset.range;
  loadHistory();
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
    else if (ev.type === "deleted" && ev.sensor_id === sensorId) {
      // This sensor was deleted elsewhere — there's nothing to show here.
      window.location.href = "/";
    }
  };
}

loadSensorMeta();
loadHistory();
connectWS();
setInterval(refreshTimes, 5000);
