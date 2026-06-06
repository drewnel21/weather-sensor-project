# Copy this file to firmware/config.py and fill in the values for your
# environment. firmware/config.py is gitignored (see project root .gitignore)
# so credentials never get committed.
#
# After editing, push it to the Pico alongside main.py and bme280.py.

# --- WiFi --------------------------------------------------------------
WIFI_SSID = "your-ssid"
WIFI_PASS = "your-password"

# --- MQTT broker -------------------------------------------------------
# Dev: point at the dev machine running Mosquitto. On Windows the loopback
# IP works only locally — for the Pico you need your machine's LAN IP
# (e.g. 192.168.1.42). Check with `ipconfig`.
# Prod: point at the Pi running Mosquitto on the LAN.
MQTT_HOST = "192.168.1.42"
MQTT_PORT = 1883

# Leave as None for an anonymous broker (Milestone 1 default).
# Milestone 7 will tighten this up with a password file in mosquitto.conf.
MQTT_USER = None
MQTT_PASS = None

# --- Identity ----------------------------------------------------------
# Topic root. Final topics will be:
#   weather/<sensor_id>/state
#   weather/<sensor_id>/status
TOPIC_PREFIX = "weather"

# sensor_id derives from machine.unique_id() automatically in main.py.
# Override here only if you want a stable, human-readable name across
# firmware re-flashes (e.g. "pico-backyard"). Leave as None to auto-derive.
SENSOR_ID_OVERRIDE = None

# --- Cadence -----------------------------------------------------------
PUBLISH_INTERVAL_S = 30

# --- I2C wiring (project confirmed: I2C0 on GP0/GP1) -------------------
I2C_BUS = 0
I2C_SDA = 0
I2C_SCL = 1
# Run firmware/i2c_scan.py once on the Pico to confirm which address your
# breakout uses; the default 0x76 covers most boards (SDO tied to GND).
BME280_ADDR = 0x76

# --- Firmware version (sent in status payload) -------------------------
FW_VERSION = "0.1.0"
