# Weather Sensor Project

Pi Pico W + BME280 outdoor environmental sensors publishing temperature, humidity, and pressure over MQTT to a self-hosted Mosquitto broker on a Raspberry Pi / Linux box. A FastAPI app on the same host persists readings to SQLite and serves a browser dashboard.

```
[Pico W + BME280] x N  --pub-->  [Mosquitto]  --sub-->  [FastAPI worker]
                                                              |
                                                              v
                                                          [SQLite]
                                                              ^
                                                              |
[Browser dashboard] <--WebSocket + REST--  [FastAPI app]
```

## Layout

- [`firmware/`](firmware/) — MicroPython firmware for the Pico W _(not started yet)_
- [`server/`](server/) — FastAPI app, MQTT subscriber, SQLite storage, dashboard
- [`deploy/`](deploy/) — Mosquitto config and systemd units for the Pi _(not started yet)_
- [`docs/`](docs/) — MQTT topic contract and other reference docs _(not started yet)_

## Current status

Milestone 2 (server skeleton) in progress. See [server/README.md](server/README.md) for setup and run instructions.

The full implementation plan lives at `~/.claude/plans/we-re-going-to-be-groovy-wadler.md`.
