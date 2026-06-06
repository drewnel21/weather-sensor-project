# Weather sensor server

FastAPI app that subscribes to MQTT readings from Pi Pico W weather sensors and persists them to SQLite. Milestone 2 of the project — no UI yet; verify via `sqlite3` or the test suite.

## Setup

Requires Python 3.11+.

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
copy .env.example .env
```

Edit `.env` to point `WEATHER_MQTT_HOST` at your broker (defaults to `localhost:1883`).

## Run

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The app starts the MQTT subscriber as a background task on startup and tears it down on shutdown. `GET /health` confirms the HTTP side is up.

## Test

```powershell
pytest
```

## Manual end-to-end with Mosquitto

With a Mosquitto broker running locally:

```powershell
# Publish a synthetic reading
mosquitto_pub -h localhost -t weather/pico-test/state -m '{\"ts\": 1700000000, \"temperature_c\": 21.3, \"humidity\": 54.2, \"pressure_hpa\": 1013.4, \"rssi\": -67}'

# Inspect the DB
sqlite3 weather.db "SELECT * FROM readings;"
sqlite3 weather.db "SELECT * FROM sensors;"
```

## Configuration

All settings are env-driven via the `WEATHER_` prefix; see `.env.example` for the full list.
