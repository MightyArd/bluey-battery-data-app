import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    log_level: str
    data_dir: str


def load() -> Settings:
    return Settings(
        mqtt_host=os.environ.get("MQTT_HOST", "core-mosquitto"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_password=os.environ.get("MQTT_PASSWORD", ""),
        log_level=os.environ.get("LOG_LEVEL", "info").upper(),
        data_dir=os.environ.get("DATA_DIR", "/data"),
    )