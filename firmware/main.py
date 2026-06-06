# Pico W weather sensor firmware.
#
# Boot path: WiFi → NTP (best-effort) → I2C/BME280 → MQTT (with LWT) → loop.
# Loop: read sensor, publish JSON state every PUBLISH_INTERVAL_S, reconnect
# on transient errors. Designed for indefinite uptime; any unrecoverable
# fault triggers machine.reset() after a short backoff so the watchdog of
# last resort is "just reboot".
#
# Wire format follows docs/topics.md: SI units (°C, hPa, %RH) in payloads.
# Display conversion (°F / inHg) happens only in the browser dashboard.

import json
import time
import binascii
import machine
import network
from machine import I2C, Pin

import config
import bme280

# umqtt.simple is NOT bundled in the current Pico W MicroPython UF2 (it was
# in older builds, but was moved out to micropython-lib around 1.20). Install
# it onto the Pico once via Thonny's Tools → Manage packages → search for
# "micropython-umqtt.simple" and click Install. Documented in README step 5a.
from umqtt.simple import MQTTClient


# --- Identity --------------------------------------------------------------

def _derive_sensor_id():
    if getattr(config, "SENSOR_ID_OVERRIDE", None):
        return config.SENSOR_ID_OVERRIDE
    # machine.unique_id() is 8 bytes on RP2040. Use the last 4 for a short,
    # readable suffix — matches the pico-a1b2c3d4 format the server expects.
    raw = machine.unique_id()
    suffix = binascii.hexlify(raw[-4:]).decode("ascii")
    return "pico-" + suffix


SENSOR_ID = _derive_sensor_id()
TOPIC_STATE = "{}/{}/state".format(config.TOPIC_PREFIX, SENSOR_ID)
TOPIC_STATUS = "{}/{}/status".format(config.TOPIC_PREFIX, SENSOR_ID)
CLIENT_ID = SENSOR_ID  # MQTT client id; broker uses this for session tracking.


# --- WiFi ------------------------------------------------------------------

def connect_wifi(timeout_s=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("WiFi: connecting to {}...".format(config.WIFI_SSID))
        wlan.connect(config.WIFI_SSID, config.WIFI_PASS)
        deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise OSError("WiFi connect timed out after {}s".format(timeout_s))
            time.sleep_ms(250)
    ip = wlan.ifconfig()[0]
    print("WiFi: connected, ip={}, rssi={}".format(ip, wlan.status("rssi")))
    return wlan, ip


# --- Time sync (best effort) ----------------------------------------------

def sync_ntp():
    # NTP gives us absolute time so payloads carry a real epoch. If it fails
    # (no DNS, no upstream), the server falls back to received_at on ingest,
    # so this is non-fatal. We still try a couple of times before giving up.
    try:
        import ntptime
        for attempt in range(3):
            try:
                ntptime.settime()
                print("NTP: synced, utc={}".format(time.time()))
                return True
            except OSError as e:
                print("NTP: attempt {} failed: {}".format(attempt + 1, e))
                time.sleep(2)
    except ImportError:
        print("NTP: ntptime module missing; skipping")
    print("NTP: giving up; server will stamp received_at")
    return False


# --- Epoch helper ----------------------------------------------------------
#
# MicroPython's time epoch is PORT-DEPENDENT. Classic bare-metal ports used
# 2000-01-01, but the rp2 build on this board (v1.28) reports 1970-01-01 —
# time.time() already returns a Unix timestamp once the RTC is set (NTP, or
# Thonny syncing the clock on connect). Hardcoding a 2000→1970 offset
# double-counted it and pushed every timestamp ~30 years into the future.
#
# Detect the epoch at runtime so this is correct on any build: time.gmtime(0)
# is the epoch instant; its year tells us whether we need the offset.
_EPOCH_YEAR = time.gmtime(0)[0]
EPOCH_OFFSET = 946684800 if _EPOCH_YEAR == 2000 else 0

def unix_epoch():
    return time.time() + EPOCH_OFFSET


# --- MQTT ------------------------------------------------------------------

def connect_mqtt(wlan, ip):
    will_payload = json.dumps({"online": False, "ip": ip})
    client = MQTTClient(
        CLIENT_ID,
        config.MQTT_HOST,
        port=config.MQTT_PORT,
        user=config.MQTT_USER,
        password=config.MQTT_PASS,
        keepalive=max(60, config.PUBLISH_INTERVAL_S * 3),
    )
    # LWT: broker auto-publishes this if our session drops without a clean
    # disconnect. Retained so a freshly-connected dashboard sees the offline
    # state immediately without waiting for the next publish window.
    client.set_last_will(TOPIC_STATUS, will_payload, retain=True, qos=1)
    client.connect()
    online_payload = json.dumps({"online": True, "ip": ip, "fw": config.FW_VERSION})
    client.publish(TOPIC_STATUS, online_payload, retain=True, qos=1)
    print("MQTT: connected to {}:{} as {}".format(config.MQTT_HOST, config.MQTT_PORT, CLIENT_ID))
    return client


# --- Sensor reads ----------------------------------------------------------

def read_payload(sensor, wlan):
    temp_c, pressure_hpa, humidity = sensor.read()
    # round() trims float noise in transit; full precision lives in
    # compensation math, not on the wire.
    payload = {
        "ts": unix_epoch(),
        "temperature_c": round(temp_c, 2),
        "pressure_hpa": round(pressure_hpa, 2),
        "humidity": round(humidity, 2) if humidity is not None else None,
        "rssi": wlan.status("rssi"),
    }
    return payload


# --- Main loop -------------------------------------------------------------

def run():
    print("--- {} firmware {} booting ---".format(SENSOR_ID, config.FW_VERSION))

    wlan, ip = connect_wifi()
    sync_ntp()

    i2c = I2C(config.I2C_BUS, sda=Pin(config.I2C_SDA), scl=Pin(config.I2C_SCL), freq=100_000)
    print("I2C: scan = {}".format([hex(a) for a in i2c.scan()]))
    sensor = bme280.BME280(i2c, address=config.BME280_ADDR)

    client = connect_mqtt(wlan, ip)

    # We sleep between cycles in small increments so a future Ctrl-C / soft
    # reset takes effect quickly. Tracking the next-publish deadline rather
    # than sleeping for the full interval avoids drift when reads vary.
    next_pub = time.ticks_ms()
    backoff_ms = 1000

    while True:
        try:
            if time.ticks_diff(time.ticks_ms(), next_pub) >= 0:
                payload = read_payload(sensor, wlan)
                body = json.dumps(payload)
                client.publish(TOPIC_STATE, body, retain=False, qos=1)
                print("pub {}: {}".format(TOPIC_STATE, body))
                next_pub = time.ticks_add(time.ticks_ms(), config.PUBLISH_INTERVAL_S * 1000)
                backoff_ms = 1000  # reset on success
            time.sleep_ms(200)

        except OSError as e:
            # Network/MQTT errors → reconnect path. Sensor-bus errors will
            # bubble up here too (I2C is wired through OSError on MicroPython).
            print("loop: OSError {}; reconnecting after {}ms".format(e, backoff_ms))
            try:
                client.disconnect()
            except Exception:
                pass
            time.sleep_ms(backoff_ms)
            backoff_ms = min(backoff_ms * 2, 30_000)
            try:
                if not wlan.isconnected():
                    wlan, ip = connect_wifi()
                client = connect_mqtt(wlan, ip)
            except OSError as e2:
                print("loop: reconnect failed: {}".format(e2))
                # Try again on next iteration; the outer while keeps us alive.

        except Exception as e:
            # Unexpected — log and reset rather than die silently. Watchdog
            # behavior is intentional for an unattended outdoor sensor.
            print("loop: fatal {}; resetting in 5s".format(e))
            time.sleep(5)
            machine.reset()


# Top-level guard so `import main` from REPL doesn't auto-start the loop.
if __name__ == "__main__":
    run()
else:
    # MicroPython runs main.py at boot — fall through to run() there too.
    run()
