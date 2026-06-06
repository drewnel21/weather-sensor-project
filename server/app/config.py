from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WEATHER_", extra="ignore")

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_prefix: str = "weather"

    db_path: Path = Path("weather.db")

    http_host: str = "0.0.0.0"
    http_port: int = 8000

    mapbox_token: str = ""
    mapbox_style: str = "mapbox://styles/mapbox/streets-v12"
