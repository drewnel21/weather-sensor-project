from pydantic import BaseModel, Field


class Reading(BaseModel):
    ts: int
    temperature_c: float | None = None
    humidity: float | None = None
    pressure_hpa: float | None = None
    rssi: int | None = None


class SensorUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class StatusPayload(BaseModel):
    """Shape of the `weather/<sensor_id>/status` retained payload.

    Firmware publishes {"online": true, "ip": "...", "fw": "..."} on connect,
    and the broker auto-publishes {"online": false, "ip": "..."} as the LWT.
    We only care about `online` for milestone 6; ip/fw are kept optional for
    forward-compat and diagnostics.
    """

    online: bool
    ip: str | None = None
    fw: str | None = None
