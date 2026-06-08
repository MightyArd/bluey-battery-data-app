#!/usr/bin/with-contenv bashio

# Pull MQTT connection details from the Supervisor MQTT service.
export MQTT_HOST="$(bashio::services mqtt 'host')"
export MQTT_PORT="$(bashio::services mqtt 'port')"
export MQTT_USER="$(bashio::services mqtt 'username')"
export MQTT_PASSWORD="$(bashio::services mqtt 'password')"
export LOG_LEVEL="$(bashio::config 'log_level')"

bashio::log.info "Starting Bluey Data Platform (MQTT ${MQTT_HOST}:${MQTT_PORT})"
exec python3 -m app.main
