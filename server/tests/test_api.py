import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_DB_PATH", str(tmp_path / "test.db"))
    # Point at an unreachable broker port so the subscriber loop fails fast and
    # doesn't actually talk to whatever Mosquitto is running locally.
    monkeypatch.setenv("WEATHER_MQTT_PORT", "1")
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_sensors_empty(client):
    r = client.get("/api/sensors")
    assert r.status_code == 200
    assert r.json() == []


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Weather Sensor Stations" in r.text


def test_readings_empty_when_unknown_sensor(client):
    r = client.get("/api/sensors/missing/readings?range=24h")
    assert r.status_code == 200
    body = r.json()
    assert body["sensor_id"] == "missing"
    assert body["range"] == "24h"
    assert body["bucket_seconds"] == 300
    assert body["points"] == []


def test_readings_rejects_invalid_range(client):
    r = client.get("/api/sensors/x/readings?range=bogus")
    assert r.status_code == 400
    assert "Invalid range" in r.json()["detail"]


def test_readings_accepts_all_three_ranges(client):
    for rng, expected_bucket in [("24h", 300), ("7d", 1800), ("30d", 7200)]:
        r = client.get(f"/api/sensors/x/readings?range={rng}")
        assert r.status_code == 200
        assert r.json()["bucket_seconds"] == expected_bucket


def test_readings_response_includes_summary(client):
    r = client.get("/api/sensors/missing/readings?range=24h")
    body = r.json()
    assert "summary" in body
    assert body["summary"] == {
        "count": 0,
        "temperature_c": None,
        "humidity": None,
        "pressure_hpa": None,
    }


def test_sensor_detail_route_serves_page(client):
    r = client.get("/sensor/pico-test")
    assert r.status_code == 200
    assert "Weather Sensor Stations" in r.text
    # The page is generic — JS extracts the id from the path.
    assert 'src="/static/sensor.js' in r.text


def test_patch_unknown_sensor_404(client):
    r = client.patch("/api/sensors/missing", json={"name": "x"})
    assert r.status_code == 404


def test_patch_empty_body_400(client):
    r = client.patch("/api/sensors/x", json={})
    assert r.status_code == 400


def test_patch_invalid_latitude_422(client):
    r = client.patch("/api/sensors/x", json={"latitude": 999})
    assert r.status_code == 422


def test_ws_accepts_connection(client):
    # ConnectionManager broadcast fan-out is covered in test_ws.py.
    # Here we just confirm the /ws endpoint accepts and registers the client.
    with client.websocket_connect("/ws"):
        assert client.app.state.manager.client_count == 1
    # leaving the context disconnects
    assert client.app.state.manager.client_count == 0


async def test_list_sensors_surfaces_online_field(client):
    # Seed via the live DB the app uses (lifespan already opened it).
    db = client.app.state.db
    await db.set_sensor_status("pico-on", True, 1_000)
    await db.set_sensor_status("pico-off", False, 1_000)

    r = client.get("/api/sensors")
    assert r.status_code == 200
    by_id = {s["sensor_id"]: s for s in r.json()}
    assert by_id["pico-on"]["online"] is True
    assert by_id["pico-off"]["online"] is False


async def test_list_sensors_online_null_when_only_state(client):
    db = client.app.state.db
    from app.models import Reading
    await db.insert_reading("pico-only-state", Reading(ts=1, temperature_c=20.0))
    body = client.get("/api/sensors").json()
    me = next(s for s in body if s["sensor_id"] == "pico-only-state")
    assert me["online"] is None


async def test_delete_sensor_endpoint(client):
    db = client.app.state.db
    from app.models import Reading
    await db.insert_reading("pico-doomed", Reading(ts=1, temperature_c=20.0))

    # Present before deletion.
    assert any(s["sensor_id"] == "pico-doomed" for s in client.get("/api/sensors").json())

    r = client.delete("/api/sensors/pico-doomed")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "deleted": "pico-doomed"}

    # Gone afterward.
    assert not any(s["sensor_id"] == "pico-doomed" for s in client.get("/api/sensors").json())


def test_delete_unknown_sensor_404(client):
    r = client.delete("/api/sensors/never-existed")
    assert r.status_code == 404
