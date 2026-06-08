"""Bluey Data Platform - entry point.

v0.1.0 scaffold: connect to MQTT and publish a heartbeat. Later increments add
the P5 fetch, the dispatch simulation, and the daily archive.
"""
import json
import logging
import os
import time

import paho.mqtt.client as mqtt

LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("bluey")

MQTT_HOST = os.environ.get("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

HEARTBEAT_TOPIC = "bluey/data_platform/heartbeat"
HEARTBEAT_INTERVAL_S = 60


def make_client() -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="bluey-data-platform"
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def main() -> None:
    log.info("Bluey Data Platform starting (MQTT %s:%s)", MQTT_HOST, MQTT_PORT)
    client = make_client()
    while True:
        payload = json.dumps({"ts": round(time.time()), "status": "alive", "version": "0.1.0"})
        client.publish(HEARTBEAT_TOPIC, payload, retain=True)
        log.info("heartbeat published")
        time.sleep(HEARTBEAT_INTERVAL_S)


if __name__ == "__main__":
    main()
