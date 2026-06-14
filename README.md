# Weather Sensor Project

Pi Pico W + BME280 outdoor environmental sensors publishing temperature,
humidity, and pressure over MQTT to a self-hosted Mosquitto broker on a
Raspberry Pi / Linux box. A FastAPI app on the same host persists readings to
SQLite and serves a live browser dashboard with a map and charts.

```
[Pico W + BME280] x N  --pub-->  [Mosquitto]  --sub-->  [FastAPI worker]
                                                              |
                                                              v
                                                          [SQLite]
                                                              ^
                                                              |
[Browser dashboard] <--WebSocket + REST--  [FastAPI app]
```

## Features

- **Live dashboard** — one card per sensor with current temp / humidity /
  pressure, updating in real time over WebSocket.
- **Mapbox GL map** — drop each sensor's pin by clicking the map; marker popups
  show live readings.
- **History charts** — per-sensor Chart.js graphs with 24h / 7d / 30d ranges,
  downsampled server-side to keep payloads small.
- **Per-sensor detail pages** — full-size charts plus min / max / avg summaries.
- **Online / offline status** — MQTT Last-Will + retained status messages drive
  a live / stale / offline badge on every card and detail page.
- **Manage sensors from the browser** — rename or delete a sensor inline; new
  sensors auto-register on their first publish, no server config needed.
- **Resilient timestamps** — the server stamps receive-time when a device's
  clock is implausible (e.g. NTP unavailable), so charts stay correct.

## Units

Wire format and storage are SI (°C, hPa, %RH) — the BME280's native units. The
dashboard converts to °F and inHg at display time only.

## Layout

- [`firmware/`](firmware/) — MicroPython firmware for the Pico W (BME280 driver,
  Wi-Fi + MQTT publish loop). Runs on real hardware. See
  [firmware/README.md](firmware/README.md).
- [`server/`](server/) — FastAPI app: aiomqtt subscriber, SQLite (WAL) storage,
  WebSocket fan-out, REST API, and the static dashboard. See
  [server/README.md](server/README.md).
- [`deploy/`](deploy/) — Mosquitto config and systemd units for the Pi.
  Currently holds the dev broker config; production artifacts are in progress.

## Status

**v1 complete.** All seven milestones are done and the stack runs in
production on a Raspberry Pi 5 — multiple Picos publishing authenticated over
MQTT, the server and broker managed by `systemd`, dashboard live on the LAN.

| # | Milestone | State |
|---|---|---|
| 1 | Firmware MVP — Pico reads BME280, publishes JSON over MQTT | ✅ Done |
| 2 | Server skeleton — FastAPI + aiomqtt subscriber + SQLite persistence | ✅ Done |
| 3 | Live dashboard — WebSocket cards per sensor | ✅ Done |
| 4 | History + charts — range-toggled Chart.js graphs | ✅ Done |
| 5 | Per-sensor detail page — full charts + min/max/avg | ✅ Done |
| 6 | Online / offline indicator — driven by MQTT status + last-seen | ✅ Done |
| 7 | Production deploy to the Pi — Mosquitto auth + systemd + walkthrough | ✅ Done |

Beyond the core plan, the dashboard also has inline **sensor rename** and
**delete**, and the map uses **Mapbox GL JS**. See [deploy/README.md](deploy/README.md)
for the Raspberry Pi setup walkthrough.

## Quick start (development)

The server runs on Windows or Linux; the runtime target is a Raspberry Pi /
Linux box on the LAN.

```bash
cd server
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"   # Windows: .venv\Scripts\python.exe
.venv/bin/python -m pytest -q                 # run the test suite
.venv/bin/python -m uvicorn app.main:app --reload
```

Then open <http://localhost:8000/>. The MQTT subscriber retries every 5s if no
broker is reachable, so the dashboard works without Mosquitto running — it just
won't receive readings. For the map, set `WEATHER_MAPBOX_TOKEN` (see
[`server/.env.example`](server/.env.example)).

To flash and provision a Pico, follow [firmware/README.md](firmware/README.md).

## Tech stack

- **Firmware:** MicroPython (`umqtt.simple`, a BME280 I²C driver)
- **Server:** FastAPI, `aiomqtt`, `aiosqlite`, `pydantic-settings`, uvicorn
- **Frontend:** plain HTML/CSS/JS, Chart.js + Mapbox GL JS via CDN (no build step)
- **Broker:** Mosquitto
- **Tests:** pytest + pytest-asyncio
