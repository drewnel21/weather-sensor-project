# Deploying to a Raspberry Pi (production)

This walks through standing up the broker + server on a Raspberry Pi on your
LAN, as `systemd` services that start on boot. Tested on a Pi 5 running
Raspberry Pi OS / Debian 13 (Trixie), Python 3.13, user `drew_admin`.

The commands use `~` (your home directory) and `$(whoami)`, so they work for
any username without editing. Where a value is genuinely site-specific (the
Pi's IP, your Mapbox token, the broker password) it's shown as a placeholder.

```
[Pico W] --auth pub--> [Mosquitto :1883] --sub--> [weather-server :8000] <-- LAN browsers
                         (systemd)                  (systemd, uvicorn)
```

## 0. Prerequisites

- Raspberry Pi OS (Bookworm or newer → Python ≥ 3.11), reachable over SSH.
- The Pi on a trusted LAN. v1 uses password auth over plain TCP, no TLS.

Give the Pi a **stable address** so the Picos and your browser can always find
it — either a static IP or a DHCP reservation in your router (recommended).
Note its IP (e.g. `192.168.1.149`) and hostname (e.g. `drew-pi5`); both are
shown by `hostname -I` and `hostname`.

## 1. Install system packages

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients python3-venv git
```

## 2. Clone the repo

```bash
git clone https://github.com/drewnel21/weather-sensor-project.git ~/weather-sensor-project
cd ~/weather-sensor-project
```

## 3. Create the Python environment

```bash
cd ~/weather-sensor-project/server
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

(No `[dev]` extras in production — that's just the test tooling.) Installing
inside the venv sidesteps Debian's "externally-managed-environment" (PEP 668)
restriction on the system Python.

## 4. Configure and secure Mosquitto

Create a broker user (you'll be prompted for a password — remember it, you'll
reuse it in step 5 and on the Picos):

```bash
sudo mosquitto_passwd -c /etc/mosquitto/passwd weather
```

Drop in the listener + auth config and restart:

```bash
sudo cp ~/weather-sensor-project/deploy/mosquitto.conf /etc/mosquitto/conf.d/weather.conf
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto
systemctl status mosquitto --no-pager
```

Quick sanity check that auth works (should print the retained messages or just
connect cleanly; a wrong password is rejected):

```bash
mosquitto_sub -h localhost -u weather -P '<the-password>' -t 'weather/#' -v &
mosquitto_pub -h localhost -u weather -P '<the-password>' -t 'weather/test/state' -m '{"ts":1,"temperature_c":20}'
# you should see the line echoed back; then: kill %1
```

## 5. Create the server `.env`

The server reads its config from `~/weather-sensor-project/.env` (loaded by the
systemd unit via `EnvironmentFile=`). Create it:

```bash
cat > ~/weather-sensor-project/.env <<EOF
WEATHER_MQTT_HOST=localhost
WEATHER_MQTT_PORT=1883
WEATHER_MQTT_USERNAME=weather
WEATHER_MQTT_PASSWORD=<the-password-from-step-4>
WEATHER_DB_PATH=$HOME/weather-sensor-project/weather.db
WEATHER_MAPBOX_TOKEN=<your-mapbox-token>
EOF
chmod 600 ~/weather-sensor-project/.env
```

Notes:
- `WEATHER_MQTT_HOST=localhost` because the server and broker run on the same
  Pi.
- `WEATHER_DB_PATH` is absolute so the database location doesn't depend on the
  service's working directory. `*.db` is gitignored, so it survives `git pull`.
- The Mapbox token is a public `pk....` token; the dashboard works without it
  (map shows a fallback). Restrict it to your Pi in the Mapbox dashboard. See
  the note at the bottom about LAN URL restrictions.

## 6. Install the server as a systemd service

The install script fills your username and repo path into the unit template,
installs it, and enables it on boot:

```bash
bash ~/weather-sensor-project/deploy/install.sh
sudo systemctl start weather-server
systemctl status weather-server --no-pager
```

Confirm it's serving locally:

```bash
curl -s http://localhost:8000/health      # -> {"status":"ok"}
```

## 7. Open the firewall (only if you run one)

Raspberry Pi OS has no firewall enabled by default — skip this unless you've
installed `ufw`. If you have:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 1883 proto tcp   # MQTT (LAN)
sudo ufw allow from 192.168.0.0/16 to any port 8000 proto tcp   # dashboard (LAN)
```

## 8. Point the Picos at the Pi

On each Pico, edit `firmware/config.py` and re-upload it (Thonny → Upload to /):

```python
MQTT_HOST = "192.168.1.149"   # the Pi's IP (or "drew-pi5.local")
MQTT_USER = "weather"
MQTT_PASS = "<the-password-from-step-4>"
```

Soft-reset each Pico (Thonny: Ctrl+D). They'll reconnect to the Pi's broker and
auto-register on the dashboard.

## 9. Verify end-to-end

- Open `http://192.168.1.149:8000/` from another device on the LAN.
- Confirm each Pico appears as a card with live values and a **live** badge.
- Place pins on the map and rename the sensors.
- **Reboot test:** `sudo reboot`, wait, then reconnect and confirm both
  services came back and data resumed:
  ```bash
  systemctl is-active mosquitto weather-server     # both -> active
  journalctl -u weather-server -n 30 --no-pager
  ```

## Updating after code changes

```bash
cd ~/weather-sensor-project
git pull
server/.venv/bin/python -m pip install -e ./server   # only if deps changed
bash deploy/install.sh                               # only if the unit changed
sudo systemctl restart weather-server
```

## Troubleshooting

- **`weather-server` won't start:** `journalctl -u weather-server -n 50`. Common
  causes: `.env` missing/unreadable, venv not created, or a typo in a path.
- **No sensor data, no errors:** the server connects but the Picos publish to a
  different broker, or auth is wrong. Check `journalctl -u mosquitto -f` while a
  Pico boots — you should see it connect and PUBLISH. A wrong `MQTT_PASS` on the
  Pico shows up as a refused connection.
- **Dashboard loads but map is blank:** no/invalid `WEATHER_MAPBOX_TOKEN`. The
  rest of the dashboard still works; fix the token and restart.
- **Readings 30 years off:** handled server-side (it stamps receive-time for
  implausible device clocks), so this shouldn't surface — but if charts look
  empty, check the device clock story in `firmware/README.md`.

## A note on the Mapbox token

Mapbox token URL restrictions are by HTTP referrer, which is awkward for a
LAN dashboard reached by IP (`http://192.168.1.149:8000/`). For a private LAN
deployment the practical options are: leave the token unrestricted (low risk —
it's only exposed to devices on your LAN), or add your Pi's URL(s) as allowed
referrers if your Mapbox plan supports it. Either way, use a **separate** token
from any you use elsewhere so you can revoke it independently.
