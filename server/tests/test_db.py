from pathlib import Path

import pytest

from app.db import Database
from app.models import Reading


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "test.db")
    await d.connect()
    yield d
    await d.close()


async def test_insert_and_read_back(db: Database):
    r = Reading(ts=1_700_000_000, temperature_c=21.3, humidity=54.2, pressure_hpa=1013.4, rssi=-67)
    await db.insert_reading("pico-aaaa", r)

    got = await db.get_last_reading("pico-aaaa")
    assert got is not None
    assert got.ts == r.ts
    assert got.temperature_c == r.temperature_c
    assert got.humidity == r.humidity
    assert got.pressure_hpa == r.pressure_hpa
    assert got.rssi == r.rssi


async def test_unknown_sensor_autoregisters(db: Database):
    r = Reading(ts=1_700_000_100, temperature_c=10.0)
    await db.insert_reading("pico-new", r)
    assert await db.get_last_reading("pico-new") is not None


async def test_latest_reading_wins(db: Database):
    await db.insert_reading("pico-a", Reading(ts=100, temperature_c=1.0))
    await db.insert_reading("pico-a", Reading(ts=200, temperature_c=2.0))
    got = await db.get_last_reading("pico-a")
    assert got is not None and got.temperature_c == 2.0


async def test_partial_payload_ok(db: Database):
    await db.insert_reading("pico-b", Reading(ts=300))  # all sensor fields null
    got = await db.get_last_reading("pico-b")
    assert got is not None
    assert got.temperature_c is None
    assert got.humidity is None


async def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "migrate.db"
    for _ in range(3):
        d = Database(path)
        await d.connect()
        await d.close()
    # Confirm the columns exist after the repeated runs.
    d = Database(path)
    await d.connect()
    await d.insert_reading("pico-x", Reading(ts=1, temperature_c=1.0))
    await d.update_sensor("pico-x", {"latitude": 40.0, "longitude": -73.0})
    rows = await d.list_sensors_with_last_reading()
    assert rows[0]["latitude"] == 40.0 and rows[0]["longitude"] == -73.0
    await d.close()


async def test_update_sensor_partial(db: Database):
    await db.insert_reading("pico-a", Reading(ts=1, temperature_c=1.0))
    assert await db.update_sensor("pico-a", {"name": "Backyard"}) is True
    rows = await db.list_sensors_with_last_reading()
    assert rows[0]["name"] == "Backyard"
    assert rows[0]["latitude"] is None  # untouched


async def test_update_sensor_unknown_returns_false(db: Database):
    assert await db.update_sensor("nope", {"name": "x"}) is False


async def test_update_sensor_rejects_unknown_fields(db: Database):
    await db.insert_reading("pico-a", Reading(ts=1, temperature_c=1.0))
    with pytest.raises(ValueError):
        await db.update_sensor("pico-a", {"sensor_id": "evil"})


async def test_update_sensor_rejects_empty(db: Database):
    await db.insert_reading("pico-a", Reading(ts=1, temperature_c=1.0))
    with pytest.raises(ValueError):
        await db.update_sensor("pico-a", {})


async def test_list_sensors_empty(db: Database):
    assert await db.list_sensors_with_last_reading() == []


async def test_get_readings_no_bucketing(db: Database):
    await db.insert_reading("pico-a", Reading(ts=100, temperature_c=10.0))
    await db.insert_reading("pico-a", Reading(ts=200, temperature_c=20.0))
    await db.insert_reading("pico-a", Reading(ts=300, temperature_c=30.0))

    points = await db.get_readings("pico-a", since=150, bucket_seconds=0)
    assert [p["ts"] for p in points] == [200, 300]
    assert [p["temperature_c"] for p in points] == [20.0, 30.0]


async def test_get_readings_with_bucketing_averages(db: Database):
    # Two readings in the same 60-second bucket, one in the next
    await db.insert_reading("pico-a", Reading(ts=600, temperature_c=10.0))
    await db.insert_reading("pico-a", Reading(ts=630, temperature_c=20.0))
    await db.insert_reading("pico-a", Reading(ts=720, temperature_c=40.0))

    points = await db.get_readings("pico-a", since=0, bucket_seconds=60)
    assert len(points) == 2
    assert points[0]["ts"] == 600 and points[0]["temperature_c"] == 15.0
    assert points[1]["ts"] == 720 and points[1]["temperature_c"] == 40.0


async def test_get_summary_empty(db: Database):
    summary = await db.get_summary("ghost", since=0)
    assert summary == {
        "count": 0,
        "temperature_c": None,
        "humidity": None,
        "pressure_hpa": None,
    }


async def test_get_summary_min_max_avg(db: Database):
    await db.insert_reading("pico-a", Reading(ts=100, temperature_c=10.0, humidity=40.0, pressure_hpa=1000.0))
    await db.insert_reading("pico-a", Reading(ts=200, temperature_c=20.0, humidity=60.0, pressure_hpa=1010.0))
    await db.insert_reading("pico-a", Reading(ts=300, temperature_c=30.0, humidity=80.0, pressure_hpa=1020.0))

    summary = await db.get_summary("pico-a", since=0)
    assert summary["count"] == 3
    assert summary["temperature_c"] == {"min": 10.0, "max": 30.0, "avg": 20.0}
    assert summary["humidity"]      == {"min": 40.0, "max": 80.0, "avg": 60.0}
    assert summary["pressure_hpa"]  == {"min": 1000.0, "max": 1020.0, "avg": 1010.0}


async def test_get_summary_excludes_other_sensors_and_old_rows(db: Database):
    await db.insert_reading("pico-a", Reading(ts=100, temperature_c=10.0))
    await db.insert_reading("pico-a", Reading(ts=200, temperature_c=30.0))
    await db.insert_reading("pico-b", Reading(ts=150, temperature_c=999.0))  # other sensor
    summary = await db.get_summary("pico-a", since=150)
    assert summary["count"] == 1
    assert summary["temperature_c"]["min"] == 30.0


async def test_get_readings_excludes_other_sensors(db: Database):
    await db.insert_reading("pico-a", Reading(ts=100, temperature_c=1.0))
    await db.insert_reading("pico-b", Reading(ts=100, temperature_c=2.0))
    points = await db.get_readings("pico-a", since=0, bucket_seconds=0)
    assert len(points) == 1 and points[0]["temperature_c"] == 1.0


async def test_list_sensors_shows_latest_reading(db: Database):
    await db.insert_reading("pico-a", Reading(ts=100, temperature_c=10.0))
    await db.insert_reading("pico-a", Reading(ts=200, temperature_c=20.0, humidity=55.0))
    await db.insert_reading("pico-b", Reading(ts=150, temperature_c=5.0))

    rows = await db.list_sensors_with_last_reading()
    by_id = {r["sensor_id"]: r for r in rows}

    assert set(by_id) == {"pico-a", "pico-b"}
    assert by_id["pico-a"]["last_reading"]["ts"] == 200
    assert by_id["pico-a"]["last_reading"]["temperature_c"] == 20.0
    assert by_id["pico-a"]["last_reading"]["humidity"] == 55.0
    assert by_id["pico-b"]["last_reading"]["ts"] == 150


# --- Online status (milestone 6) ----------------------------------------

async def test_list_sensors_online_unknown_for_state_only_sensor(db: Database):
    # A sensor that's only ever published state messages has no online flag —
    # `null` is the wire representation for "we don't know yet".
    await db.insert_reading("pico-a", Reading(ts=1, temperature_c=1.0))
    rows = await db.list_sensors_with_last_reading()
    assert rows[0]["online"] is None


async def test_set_sensor_status_upserts_and_flips_flag(db: Database):
    # Status can arrive before any state (Pico publishes online=true on
    # connect, before its first reading). Confirm the sensor row is created
    # and the online flag is set.
    await db.set_sensor_status("pico-fresh", True, 1_000)
    rows = await db.list_sensors_with_last_reading()
    by_id = {r["sensor_id"]: r for r in rows}
    assert by_id["pico-fresh"]["online"] is True
    assert by_id["pico-fresh"]["last_seen"] == 1_000
    # last_reading remains None because no state has arrived.
    assert by_id["pico-fresh"]["last_reading"] is None

    # LWT fires; the flag flips to false and last_seen advances.
    await db.set_sensor_status("pico-fresh", False, 2_000)
    rows = await db.list_sensors_with_last_reading()
    by_id = {r["sensor_id"]: r for r in rows}
    assert by_id["pico-fresh"]["online"] is False
    assert by_id["pico-fresh"]["last_seen"] == 2_000


async def test_set_sensor_status_after_existing_readings(db: Database):
    # Pre-existing sensor with readings, then a status message arrives.
    await db.insert_reading("pico-a", Reading(ts=500, temperature_c=10.0))
    await db.set_sensor_status("pico-a", False, 1_500)
    rows = await db.list_sensors_with_last_reading()
    by_id = {r["sensor_id"]: r for r in rows}
    assert by_id["pico-a"]["online"] is False
    assert by_id["pico-a"]["last_seen"] == 1_500
    # Reading history is untouched.
    assert by_id["pico-a"]["last_reading"]["ts"] == 500


# --- Delete sensor -------------------------------------------------------

async def test_delete_sensor_removes_sensor_and_readings(db: Database):
    await db.insert_reading("pico-a", Reading(ts=100, temperature_c=1.0))
    await db.insert_reading("pico-a", Reading(ts=200, temperature_c=2.0))
    await db.insert_reading("pico-b", Reading(ts=100, temperature_c=9.0))

    assert await db.delete_sensor("pico-a") is True

    rows = await db.list_sensors_with_last_reading()
    assert {r["sensor_id"] for r in rows} == {"pico-b"}
    # Readings for the deleted sensor are gone too.
    assert await db.get_readings("pico-a", since=0, bucket_seconds=0) == []
    # The other sensor is untouched.
    assert await db.get_last_reading("pico-b") is not None


async def test_delete_unknown_sensor_returns_false(db: Database):
    assert await db.delete_sensor("ghost") is False
