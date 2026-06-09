"""MQTT discovery and state publishing for Bluey Data Platform.

run_id is carried as a JSON attribute on sensor.p5_price_forecast rather than
as a separate companion sensor. This keeps the entity count low; the run_id is
accessible via the sensor's attributes in HA templates and automations.
"""
from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from .p5 import P5Result

log = logging.getLogger("bluey.publisher")

_DEVICE = {
    "identifiers": ["bluey_data_platform"],
    "name": "Bluey Data Platform",
    "model": "data-platform v0.2.0",
    "manufacturer": "Bluey",
}

_DISCOVERY_TOPIC = "homeassistant/sensor/bluey_p5_price_forecast/config"
_STATE_TOPIC = "bluey/data_platform/p5_price_forecast/state"
_HEARTBEAT_TOPIC = "bluey/data_platform/heartbeat"


def publish_discovery(client: mqtt.Client) -> None:
    """Publish retained MQTT discovery config for sensor.p5_price_forecast."""
    config = {
        "name": "P5 Price Forecast",
        "unique_id": "bluey_p5_price_forecast",
        "state_class": "measurement",
        "unit_of_measurement": "$/MWh",
        "state_topic": _STATE_TOPIC,
        "value_template": "{{ value_json.rrp }}",
        "json_attributes_topic": _STATE_TOPIC,
        "json_attributes_template": "{{ {'run_id': value_json.run_id} | tojson }}",
        "availability_topic": _HEARTBEAT_TOPIC,
        "availability_template": "{{ 'online' if value_json.status == 'alive' else 'offline' }}",
        "device": _DEVICE,
    }
    client.publish(_DISCOVERY_TOPIC, json.dumps(config), retain=True)
    log.debug("Discovery config published to %s", _DISCOVERY_TOPIC)


def publish_p5(client: mqtt.Client, result: P5Result) -> None:
    """Publish current P5 price state. run_id is included as a JSON attribute."""
    payload = json.dumps({"rrp": result.rrp, "run_id": result.run_datetime})
    client.publish(_STATE_TOPIC, payload, retain=True)
    log.debug("P5 state published: %s", payload)