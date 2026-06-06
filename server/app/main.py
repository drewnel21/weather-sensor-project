import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .db import Database
from .models import SensorUpdate
from .mqtt_client import run_subscriber
from .ws import ConnectionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# (window_seconds, bucket_seconds). bucket=0 means no downsampling.
RANGES: dict[str, tuple[int, int]] = {
    "24h": (24 * 3600, 5 * 60),
    "7d": (7 * 86400, 30 * 60),
    "30d": (30 * 86400, 2 * 3600),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = Database(settings.db_path)
    await db.connect()
    manager = ConnectionManager()

    stop = asyncio.Event()
    sub_task = asyncio.create_task(run_subscriber(settings, db, manager, stop))

    app.state.settings = settings
    app.state.db = db
    app.state.manager = manager
    try:
        yield
    finally:
        stop.set()
        sub_task.cancel()
        try:
            await sub_task
        except asyncio.CancelledError:
            pass
        await db.close()


app = FastAPI(title="Weather sensor server", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    settings: Settings = app.state.settings
    return {
        "mapbox_token": settings.mapbox_token,
        "mapbox_style": settings.mapbox_style,
    }


@app.get("/api/sensors")
async def list_sensors():
    db: Database = app.state.db
    return await db.list_sensors_with_last_reading()


@app.patch("/api/sensors/{sensor_id}")
async def update_sensor(sensor_id: str, update: SensorUpdate):
    fields = update.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    db: Database = app.state.db
    found = await db.update_sensor(sensor_id, fields)
    if not found:
        raise HTTPException(404, f"Unknown sensor: {sensor_id}")
    return {"ok": True, "updated": list(fields)}


@app.delete("/api/sensors/{sensor_id}")
async def delete_sensor(sensor_id: str):
    db: Database = app.state.db
    found = await db.delete_sensor(sensor_id)
    if not found:
        raise HTTPException(404, f"Unknown sensor: {sensor_id}")
    # Tell every open dashboard to drop the card immediately, so deletion
    # propagates without a manual refresh.
    manager: ConnectionManager = app.state.manager
    await manager.broadcast({"type": "deleted", "sensor_id": sensor_id})
    return {"ok": True, "deleted": sensor_id}


@app.get("/api/sensors/{sensor_id}/readings")
async def get_sensor_readings(sensor_id: str, range: str = "24h"):
    cfg = RANGES.get(range)
    if cfg is None:
        raise HTTPException(400, f"Invalid range '{range}'. Use one of: {', '.join(RANGES)}")
    window, bucket = cfg
    since = int(time.time()) - window
    db: Database = app.state.db
    points = await db.get_readings(sensor_id, since, bucket)
    summary = await db.get_summary(sensor_id, since)
    return {
        "sensor_id": sensor_id,
        "range": range,
        "bucket_seconds": bucket,
        "points": points,
        "summary": summary,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    manager: ConnectionManager = ws.app.state.manager
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


class _NoCacheStatic(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


app.mount("/static", _NoCacheStatic(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sensor/{sensor_id}")
async def sensor_detail(sensor_id: str):
    return FileResponse(STATIC_DIR / "sensor.html")
