"""MQTT discovery and state publishing for Bluey Data Platform."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .p5 import P5Result

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

log = logging.getLogger("bluey.publisher")

_DEVICE = {
    "identifiers": ["bluey_data_platform"],
    "name": "Bluey Data Platform",
    "model": "data-platform v0.5.1",
    "manufacturer": "Bluey",
}

_DISCOVERY_P5 = "homeassistant/sensor/bluey_p5_price_forecast/config"
_STATE_P5 = "bluey/data_platform/p5_price_forecast/state"
_HEARTBEAT = "bluey/data_platform/heartbeat"

_DISCOVERY_SIM_SOC = "homeassistant/sensor/bluey_simulation_soc/config"
_DISCOVERY_SIM_PLANNED = "homeassistant/sensor/bluey_simulation_planned_mode/config"
_DISCOVERY_SIM_SETTLED = "homeassistant/sensor/bluey_simulation_settled_mode/config"
_DISCOVERY_SIM_GRID = "homeassistant/sensor/bluey_simulation_grid_signed/config"

_STATE_SIM_SOC = "bluey/data_platform/simulation_soc/state"
_STATE_SIM_PLANNED = "bluey/data_platform/simulation_planned_mode/state"
_STATE_SIM_SETTLED = "bluey/data_platform/simulation_settled_mode/state"
_STATE_SIM_GRID = "bluey/data_platform/simulation_grid_signed/state"

_DISCOVERY_BACKUP_NAS = "homeassistant/sensor/bluey_backup_nas_last_success/config"
_DISCOVERY_BACKUP_CLOUD = "homeassistant/sensor/bluey_backup_cloud_last_success/config"
_STATE_BACKUP_NAS = "bluey/data_platform/backup_nas_last_success/state"
_STATE_BACKUP_CLOUD = "bluey/data_platform/backup_cloud_last_success/state"

# Force-backup button. A momentary HA button: pressing it publishes the press
# payload to the command topic, which the main loop turns into one archive run.
# The command topic is public so main.py can subscribe to it.
_DISCOVERY_BUTTON = "homeassistant/button/bluey_run_archive/config"
RUN_ARCHIVE_COMMAND_TOPIC = "bluey/data_platform/run_archive/command"
RUN_ARCHIVE_PRESS_PAYLOAD = "PRESS"

_SIM_MODES = ["charge", "discharge", "self_consume", "idle"]


def publish_discovery(client: mqtt.Client) -> None:
    """Publish retained MQTT discovery configs for all entities."""
    _publish_p5_discovery(client)
    _publish_simulation_discovery(client)
    _publish_backup_discovery(client)
    _publish_button_discovery(client)


def _publish_p5_discovery(client: mqtt.Client) -> None:
    config = {
        "name": "P5 Price Forecast",
        "unique_id": "bluey_p5_price_forecast",
        "state_class": "measurement",
        "unit_of_measurement": "$/MWh",
        "state_topic": _STATE_P5,
        "value_template": "{{ value_json.rrp }}",
        "json_attributes_topic": _STATE_P5,
        "json_attributes_template": "{{ {'run_id': value_json.run_id} | tojson }}",
        "availability_topic": _HEARTBEAT,
        "availability_template": "{{ 'online' if value_json.status == 'alive' else 'offline' }}",
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_P5, json.dumps(config), retain=True)
    log.debug("P5 discovery published")


def _publish_simulation_discovery(client: mqtt.Client) -> None:
    avail = {"topic": _HEARTBEAT, "value_template": "{{ 'online' if value_json.status == 'alive' else 'offline' }}"}

    soc_cfg = {
        "name": "Simulation SOC",
        "unique_id": "bluey_simulation_soc",
        "device_class": "battery",
        "state_class": "measurement",
        "unit_of_measurement": "%",
        "state_topic": _STATE_SIM_SOC,
        "availability": [avail],
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_SIM_SOC, json.dumps(soc_cfg), retain=True)

    planned_cfg = {
        "name": "Simulation Planned Mode",
        "unique_id": "bluey_simulation_planned_mode",
        "device_class": "enum",
        "options": _SIM_MODES,
        "state_topic": _STATE_SIM_PLANNED,
        "availability": [avail],
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_SIM_PLANNED, json.dumps(planned_cfg), retain=True)

    settled_cfg = {
        "name": "Simulation Settled Mode",
        "unique_id": "bluey_simulation_settled_mode",
        "device_class": "enum",
        "options": _SIM_MODES,
        "state_topic": _STATE_SIM_SETTLED,
        "availability": [avail],
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_SIM_SETTLED, json.dumps(settled_cfg), retain=True)

    grid_cfg = {
        "name": "Simulation Grid Signed",
        "unique_id": "bluey_simulation_grid_signed",
        "device_class": "power",
        "state_class": "measurement",
        "unit_of_measurement": "W",
        "state_topic": _STATE_SIM_GRID,
        "availability": [avail],
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_SIM_GRID, json.dumps(grid_cfg), retain=True)
    log.debug("Simulation discovery published")


def _publish_backup_discovery(client: mqtt.Client) -> None:
    avail = {"topic": _HEARTBEAT, "value_template": "{{ 'online' if value_json.status == 'alive' else 'offline' }}"}

    nas_cfg = {
        "name": "Backup NAS Last Success",
        "unique_id": "bluey_backup_nas_last_success",
        "device_class": "timestamp",
        "state_topic": _STATE_BACKUP_NAS,
        "availability": [avail],
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_BACKUP_NAS, json.dumps(nas_cfg), retain=True)

    cloud_cfg = {
        "name": "Backup Cloud Last Success",
        "unique_id": "bluey_backup_cloud_last_success",
        "device_class": "timestamp",
        "state_topic": _STATE_BACKUP_CLOUD,
        "availability": [avail],
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_BACKUP_CLOUD, json.dumps(cloud_cfg), retain=True)
    log.debug("Backup health discovery published")


def _publish_button_discovery(client: mqtt.Client) -> None:
    """Publish the retained discovery config for the Force backup button.

    object_id "run_archive" under the "Bluey Data Platform" device yields the
    entity_id button.bluey_data_platform_run_archive, while the friendly name stays
    "Force backup". availability mirrors the other entities (online while the
    heartbeat says alive).
    """
    avail = {"topic": _HEARTBEAT, "value_template": "{{ 'online' if value_json.status == 'alive' else 'offline' }}"}

    button_cfg = {
        "name": "Force backup",
        "object_id": "run_archive",
        "unique_id": "bluey_run_archive",
        "command_topic": RUN_ARCHIVE_COMMAND_TOPIC,
        "payload_press": RUN_ARCHIVE_PRESS_PAYLOAD,
        "icon": "mdi:cloud-upload",
        "availability": [avail],
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_BUTTON, json.dumps(button_cfg), retain=True)
    log.debug("Force-backup button discovery published")


def publish_backup_health(client: mqtt.Client, dest: str, ts_iso: str) -> None:
    """Publish a backup-health timestamp for a destination after a verified push.

    `dest` is "nas" or "cloud"; `ts_iso` is an ISO8601 timestamp.
    """
    topic = _STATE_BACKUP_NAS if dest == "nas" else _STATE_BACKUP_CLOUD
    client.publish(topic, ts_iso, retain=True)
    log.info("Backup health published: dest=%s ts=%s", dest, ts_iso)


def publish_p5(client: mqtt.Client, result: P5Result) -> None:
    """Publish current P5 price state with run_id as a JSON attribute."""
    payload = json.dumps({"rrp": result.rrp, "run_id": result.run_datetime})
    client.publish(_STATE_P5, payload, retain=True)
    log.debug("P5 state published: %s", payload)


def publish_simulation_settled(client: mqtt.Client, result: object) -> None:
    """Publish settled simulation outputs (SOC, settled mode, grid power)."""
    client.publish(_STATE_SIM_SOC, f"{result.new_soc:.2f}", retain=True)
    client.publish(_STATE_SIM_SETTLED, result.settled_mode, retain=True)
    client.publish(_STATE_SIM_GRID, f"{result.grid_signed_w:.1f}", retain=True)
    log.debug("Simulation settled published: soc=%.2f mode=%s grid=%.1f",
              result.new_soc, result.settled_mode, result.grid_signed_w)


def publish_simulation_planned(client: mqtt.Client, mode: str) -> None:
    """Publish the planned mode for the upcoming period."""
    client.publish(_STATE_SIM_PLANNED, mode, retain=True)
    log.debug("Simulation planned mode published: %s", mode)