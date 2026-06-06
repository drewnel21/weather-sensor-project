import time
from pathlib import Path

import aiosqlite

from .models import Reading

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensors (
  sensor_id  TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  location   TEXT,
  added_at   INTEGER NOT NULL,
  last_seen  INTEGER
);

CREATE TABLE IF NOT EXISTS readings (
  sensor_id      TEXT NOT NULL REFERENCES sensors(sensor_id),
  ts             INTEGER NOT NULL,
  temperature_c  REAL,
  humidity       REAL,
  pressure_hpa   REAL,
  rssi           INTEGER,
  PRIMARY KEY (sensor_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(SCHEMA)
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        """Idempotent column additions for older DB files."""
        db = self._db
        assert db is not None
        async with db.execute("PRAGMA table_info(sensors)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        for new_col in ("latitude", "longitude"):
            if new_col not in cols:
                await db.execute(f"ALTER TABLE sensors ADD COLUMN {new_col} REAL")
        # online: NULL means we've never observed a status message for this
        # sensor (auto-registered from a state message before the broker
        # delivered the retained status). 1 = online, 0 = offline (LWT fired).
        if "online" not in cols:
            await db.execute("ALTER TABLE sensors ADD COLUMN online INTEGER")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def insert_reading(self, sensor_id: str, r: Reading) -> None:
        db = self._db
        if db is None:
            raise RuntimeError("Database is not connected")
        now = int(time.time())
        await db.execute(
            "INSERT OR IGNORE INTO sensors (sensor_id, name, added_at, last_seen) VALUES (?, ?, ?, ?)",
            (sensor_id, sensor_id, now, now),
        )
        await db.execute(
            "UPDATE sensors SET last_seen = ? WHERE sensor_id = ?",
            (now, sensor_id),
        )
        await db.execute(
            "INSERT OR REPLACE INTO readings"
            " (sensor_id, ts, temperature_c, humidity, pressure_hpa, rssi)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (sensor_id, r.ts, r.temperature_c, r.humidity, r.pressure_hpa, r.rssi),
        )
        await db.commit()

    async def set_sensor_status(self, sensor_id: str, online: bool, ts: int) -> None:
        """Upsert sensor row and set its online flag + last_seen.

        Called from the MQTT status handler. Status messages can arrive before
        any state message (e.g. the Pico publishes online=true on connect,
        before its first 30s reading), so we INSERT OR IGNORE the sensor row
        the same way insert_reading does.
        """
        db = self._db
        if db is None:
            raise RuntimeError("Database is not connected")
        await db.execute(
            "INSERT OR IGNORE INTO sensors (sensor_id, name, added_at, last_seen, online)"
            " VALUES (?, ?, ?, ?, ?)",
            (sensor_id, sensor_id, ts, ts, 1 if online else 0),
        )
        await db.execute(
            "UPDATE sensors SET online = ?, last_seen = ? WHERE sensor_id = ?",
            (1 if online else 0, ts, sensor_id),
        )
        await db.commit()

    async def get_last_reading(self, sensor_id: str) -> Reading | None:
        db = self._db
        if db is None:
            raise RuntimeError("Database is not connected")
        async with db.execute(
            "SELECT ts, temperature_c, humidity, pressure_hpa, rssi FROM readings"
            " WHERE sensor_id = ? ORDER BY ts DESC LIMIT 1",
            (sensor_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return Reading(
            ts=row[0],
            temperature_c=row[1],
            humidity=row[2],
            pressure_hpa=row[3],
            rssi=row[4],
        )

    async def get_readings(
        self, sensor_id: str, since: int, bucket_seconds: int
    ) -> list[dict]:
        """Time-ordered readings since `since` (epoch s).

        If bucket_seconds > 0, downsamples by averaging within fixed-size buckets.
        """
        db = self._db
        if db is None:
            raise RuntimeError("Database is not connected")
        if bucket_seconds > 0:
            sql = (
                "SELECT (ts / ?) * ? AS bucket,"
                "       AVG(temperature_c), AVG(humidity), AVG(pressure_hpa) "
                "FROM readings "
                "WHERE sensor_id = ? AND ts >= ? "
                "GROUP BY bucket "
                "ORDER BY bucket"
            )
            params: tuple = (bucket_seconds, bucket_seconds, sensor_id, since)
        else:
            sql = (
                "SELECT ts, temperature_c, humidity, pressure_hpa "
                "FROM readings "
                "WHERE sensor_id = ? AND ts >= ? "
                "ORDER BY ts"
            )
            params = (sensor_id, since)
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [
            {
                "ts": int(row[0]),
                "temperature_c": row[1],
                "humidity": row[2],
                "pressure_hpa": row[3],
            }
            for row in rows
        ]

    async def get_summary(self, sensor_id: str, since: int) -> dict:
        """min/max/avg per metric, computed from RAW rows (never bucketed)."""
        db = self._db
        if db is None:
            raise RuntimeError("Database is not connected")
        async with db.execute(
            "SELECT COUNT(*),"
            "       MIN(temperature_c), MAX(temperature_c), AVG(temperature_c),"
            "       MIN(humidity),      MAX(humidity),      AVG(humidity),"
            "       MIN(pressure_hpa),  MAX(pressure_hpa),  AVG(pressure_hpa) "
            "FROM readings WHERE sensor_id = ? AND ts >= ?",
            (sensor_id, since),
        ) as cur:
            row = await cur.fetchone()
        count = row[0] if row else 0
        return {
            "count": count,
            "temperature_c": {"min": row[1], "max": row[2], "avg": row[3]} if count else None,
            "humidity":      {"min": row[4], "max": row[5], "avg": row[6]} if count else None,
            "pressure_hpa":  {"min": row[7], "max": row[8], "avg": row[9]} if count else None,
        }

    async def list_sensors_with_last_reading(self) -> list[dict]:
        db = self._db
        if db is None:
            raise RuntimeError("Database is not connected")
        async with db.execute(
            """
            SELECT s.sensor_id, s.name, s.location, s.latitude, s.longitude,
                   s.last_seen, s.online,
                   r.ts, r.temperature_c, r.humidity, r.pressure_hpa, r.rssi
            FROM sensors s
            LEFT JOIN readings r
              ON r.sensor_id = s.sensor_id
             AND r.ts = (SELECT MAX(ts) FROM readings WHERE sensor_id = s.sensor_id)
            ORDER BY s.name
            """
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            last_reading = None
            if row[7] is not None:
                last_reading = {
                    "ts": row[7],
                    "temperature_c": row[8],
                    "humidity": row[9],
                    "pressure_hpa": row[10],
                    "rssi": row[11],
                }
            # online: stored as 0/1/NULL; surface as true/false/null so the
            # client can distinguish "never observed" from "observed offline".
            online_raw = row[6]
            online = None if online_raw is None else bool(online_raw)
            result.append({
                "sensor_id": row[0],
                "name": row[1],
                "location": row[2],
                "latitude": row[3],
                "longitude": row[4],
                "last_seen": row[5],
                "online": online,
                "last_reading": last_reading,
            })
        return result

    async def delete_sensor(self, sensor_id: str) -> bool:
        """Delete a sensor and all of its readings. Returns True if it existed.

        Readings are removed first: the schema declares a foreign key from
        readings → sensors and the connection runs with foreign_keys=ON, so the
        parent row can't be dropped while children remain.
        """
        db = self._db
        if db is None:
            raise RuntimeError("Database is not connected")
        await db.execute("DELETE FROM readings WHERE sensor_id = ?", (sensor_id,))
        cur = await db.execute("DELETE FROM sensors WHERE sensor_id = ?", (sensor_id,))
        await db.commit()
        return cur.rowcount > 0

    _UPDATABLE_FIELDS = {"name", "location", "latitude", "longitude"}

    async def update_sensor(self, sensor_id: str, fields: dict) -> bool:
        """Apply a partial update. Returns True if the sensor row exists."""
        db = self._db
        if db is None:
            raise RuntimeError("Database is not connected")
        bad = set(fields) - self._UPDATABLE_FIELDS
        if bad:
            raise ValueError(f"Cannot update fields: {sorted(bad)}")
        if not fields:
            raise ValueError("No fields to update")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [sensor_id]
        cur = await db.execute(
            f"UPDATE sensors SET {assignments} WHERE sensor_id = ?", values
        )
        await db.commit()
        return cur.rowcount > 0
