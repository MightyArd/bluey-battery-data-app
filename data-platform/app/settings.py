import os
from dataclasses import dataclass


def _parse_hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


@dataclass(frozen=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    log_level: str
    data_dir: str
    # Simulation windows (local time)
    charge_window_start_h: int
    charge_window_start_m: int
    charge_window_end_h: int
    charge_window_end_m: int
    export_window_start_h: int
    export_window_start_m: int
    export_window_end_h: int
    export_window_end_m: int
    # Simulation parameters
    reserve_target_soc: int
    price_override_threshold: float
    export_limit_w: int
    usable_capacity_kwh: float
    max_charge_kw: float
    soc_hard_min: int
    soc_hard_max: int
    # Entities
    soc_entity: str
    solar_entity: str
    reserve_load_entity: str
    # InfluxDB
    influxdb_token: str
    # Timezone
    timezone: str
    # Daily archive
    archive_hour: int
    archive_minute: int
    # Synology NAS (SMB) destination
    nas_host: str
    nas_share: str
    nas_path: str
    nas_user: str
    nas_password: str
    # Backblaze B2 (S3-compatible) destination
    b2_bucket: str
    b2_key_id: str
    b2_key: str
    b2_endpoint: str


def load() -> Settings:
    cws_h, cws_m = _parse_hm(os.environ.get("CHARGE_WINDOW_START", "11:00"))
    cwe_h, cwe_m = _parse_hm(os.environ.get("CHARGE_WINDOW_END", "14:00"))
    ews_h, ews_m = _parse_hm(os.environ.get("EXPORT_WINDOW_START", "18:00"))
    ewe_h, ewe_m = _parse_hm(os.environ.get("EXPORT_WINDOW_END", "21:00"))
    arch_h, arch_m = _parse_hm(os.environ.get("ARCHIVE_TIME", "00:30"))
    return Settings(
        mqtt_host=os.environ.get("MQTT_HOST", "core-mosquitto"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_password=os.environ.get("MQTT_PASSWORD", ""),
        log_level=os.environ.get("LOG_LEVEL", "info").upper(),
        data_dir=os.environ.get("DATA_DIR", "/data"),
        charge_window_start_h=cws_h,
        charge_window_start_m=cws_m,
        charge_window_end_h=cwe_h,
        charge_window_end_m=cwe_m,
        export_window_start_h=ews_h,
        export_window_start_m=ews_m,
        export_window_end_h=ewe_h,
        export_window_end_m=ewe_m,
        reserve_target_soc=int(os.environ.get("RESERVE_TARGET_SOC", "15")),
        price_override_threshold=float(os.environ.get("PRICE_OVERRIDE_THRESHOLD", "500")),
        export_limit_w=int(os.environ.get("EXPORT_LIMIT_W", "500")),
        usable_capacity_kwh=float(os.environ.get("USABLE_CAPACITY_KWH", "40.0")),
        max_charge_kw=float(os.environ.get("MAX_CHARGE_KW", "6.5")),
        soc_hard_min=int(os.environ.get("SOC_HARD_MIN", "5")),
        soc_hard_max=int(os.environ.get("SOC_HARD_MAX", "100")),
        soc_entity=os.environ.get("SOC_ENTITY", "sensor.goodwe_battery_state_of_charge"),
        solar_entity=os.environ.get("SOLAR_ENTITY", "sensor.goodwe_pv_power_total"),
        reserve_load_entity=os.environ.get("RESERVE_LOAD_ENTITY", "sensor.goodwe_house_consumption"),
        influxdb_token=os.environ.get("INFLUXDB_TOKEN", ""),
        timezone=os.environ.get("TIMEZONE", "Australia/Melbourne"),
        archive_hour=arch_h,
        archive_minute=arch_m,
        nas_host=os.environ.get("NAS_HOST", "192.168.50.214"),
        nas_share=os.environ.get("NAS_SHARE", ""),
        nas_path=os.environ.get("NAS_PATH", "energy-archive"),
        nas_user=os.environ.get("NAS_USER", ""),
        nas_password=os.environ.get("NAS_PASSWORD", ""),
        b2_bucket=os.environ.get("B2_BUCKET", ""),
        b2_key_id=os.environ.get("B2_KEY_ID", ""),
        b2_key=os.environ.get("B2_KEY", ""),
        b2_endpoint=os.environ.get("B2_ENDPOINT", ""),
    )