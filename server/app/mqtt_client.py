import asyncio
import json
import logging
import time
from typing import Literal

import aiomqtt
from pydantic import ValidationError

from .config import Settings
from .db import Database
from .models import Reading, StatusPayload
from .ws import ConnectionManager

log = logging.getLogger(__name__)

TopicKind = Literal["state", "status"]

# A Pico that couldn't reach an NTP server reports time anchored to the RP2040's
# 2000-01-01 boot epoch — roughly 26 years in the past — which would bury every
# reading outside the dashboard's 24h/7d/30d windows. When a device's clock is
# implausibly far from ours, the server's receive time is authoritative (at a
# 30s LAN publish cadence, receive time is within milliseconds of the actual
# sensor read anyway). The skew tolerance is deliberately generous so a
# correctly NTP-synced device keeps its own, more precise timestamp.
MAX_CLOCK_SKEW_S = 86400  # 1 day


def authoritative_ts(device_ts: int, received_at: int) -> int:
    """Pick the trustworthy timestamp for a reading.

    Returns the device's own ts when it's within MAX_CLOCK_SKEW_S of the
    server clock; otherwise falls back to the server's receive time.
    """
    if abs(received_at - device_ts) > MAX_CLOCK_SKEW_S:
        return received_at
    return device_ts


def parse_topic(topic: str, prefix: str) -> tuple[str, TopicKind] | None:
    """Return (sensor_id, kind) for a topic of the form `<prefix>/<sensor_id>/<state|status>`.

    Returns None for anything else — including topics with the right shape but
    an unknown trailing segment. This is the choke point that decides what the
    rest of the subscriber even looks at, so be strict.
    """
    head = prefix + "/"
    if not topic.startswith(head):
        return None
    rest = topic[len(head):]
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0]:
        return None
    kind = parts[1]
    if kind not in ("state", "status"):
        return None
    return parts[0], kind  # type: ignore[return-value]


def parse_reading(payload: bytes) -> Reading | None:
    try:
        data = json.loads(payload)
        return Reading.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        log.warning("Discarding invalid state payload: %s", e)
        return None


def parse_status(payload: bytes) -> StatusPayload | None:
    # LWT publishes with an empty payload in some broker configs (rare), and
    # the firmware always sets a JSON body — so empty is invalid here.
    if not payload:
        log.warning("Discarding empty status payload")
        return None
    try:
        data = json.loads(payload)
        return StatusPayload.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        log.warning("Discarding invalid status payload: %s", e)
        return None


async def _handle_state(
    sensor_id: str, payload: bytes, db: Database, manager: ConnectionManager
) -> None:
    reading = parse_reading(payload)
    if reading is None:
        return
    # Correct an implausible device clock before anything downstream sees it,
    # so the DB row and the live WS broadcast carry the same authoritative ts.
    received_at = int(time.time())
    corrected = authoritative_ts(reading.ts, received_at)
    if corrected != reading.ts:
        log.warning(
            "Sensor %s clock off (device ts=%d); stamping received_at=%d",
            sensor_id, reading.ts, corrected,
        )
        reading.ts = corrected
    await db.insert_reading(sensor_id, reading)
    await manager.broadcast({
        "type": "reading",
        "sensor_id": sensor_id,
        "ts": reading.ts,
        "temperature_c": reading.temperature_c,
        "humidity": reading.humidity,
        "pressure_hpa": reading.pressure_hpa,
        "rssi": reading.rssi,
    })
    log.info("Stored reading from %s @ ts=%d", sensor_id, reading.ts)


async def _handle_status(
    sensor_id: str, payload: bytes, db: Database, manager: ConnectionManager
) -> None:
    status = parse_status(payload)
    if status is None:
        return
    # last_seen for status reflects "the broker told us about this device just
    # now" — that's an interesting timestamp even when the message says
    # online=false (it's the moment LWT fired).
    now = int(time.time())
    await db.set_sensor_status(sensor_id, status.online, now)
    await manager.broadcast({
        "type": "status",
        "sensor_id": sensor_id,
        "online": status.online,
        "ts": now,
        "ip": status.ip,
        "fw": status.fw,
    })
    log.info(
        "Sensor %s reported online=%s (ip=%s, fw=%s)",
        sensor_id, status.online, status.ip, status.fw,
    )


async def run_subscriber(
    settings: Settings,
    db: Database,
    manager: ConnectionManager,
    stop: asyncio.Event,
) -> None:
    # Single wildcard catches both state and status; parse_topic decides which
    # branch to take. Cleaner than two separate subscribe calls and one async
    # iterator per topic.
    topic = f"{settings.mqtt_topic_prefix}/+/+"
    reconnect_delay = 5.0
    while not stop.is_set():
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_username,
                password=settings.mqtt_password,
            ) as client:
                await client.subscribe(topic)
                log.info("MQTT subscribed to %s", topic)
                async for message in client.messages:
                    parsed = parse_topic(str(message.topic), settings.mqtt_topic_prefix)
                    if parsed is None:
                        continue
                    sensor_id, kind = parsed
                    payload = bytes(message.payload)
                    if kind == "state":
                        await _handle_state(sensor_id, payload, db, manager)
                    else:  # "status"
                        await _handle_status(sensor_id, payload, db, manager)
        except aiomqtt.MqttError as e:
            log.warning("MQTT error: %s — reconnecting in %.0fs", e, reconnect_delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=reconnect_delay)
            except asyncio.TimeoutError:
                pass
