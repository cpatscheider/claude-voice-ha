"""Constants for the Claude Voice integration."""

from __future__ import annotations

import logging

DOMAIN = "claude_voice"
LOGGER = logging.getLogger(__package__)

CONF_URL = "url"
CONF_TOKEN = "token"

CONF_DOMAINS = "domains"
CONF_SENSOR_CLASSES = "sensor_device_classes"
CONF_MAX_ENTITIES = "max_entities"
CONF_AREA_FIRST = "speaker_area_first"
CONF_FALLBACK_AGENT = "fallback_agent"

DEFAULT_URL = "http://claude-voice.default.svc.cluster.local:8765"

# The base prompt tells Claude the weather is "Forecast Home" in <state>, so weather is a default.
DEFAULT_DOMAINS = [
    "light",
    "switch",
    "cover",
    "climate",
    "fan",
    "media_player",
    "scene",
    "lock",
    "weather",
    "sensor",
]
# Sensors are the bulk of any install. Only the classes people ask about by voice go in; anything
# else Claude can still fetch with GetLiveContext.
DEFAULT_SENSOR_CLASSES = ["temperature", "humidity"]
DEFAULT_MAX_ENTITIES = 150
DEFAULT_AREA_FIRST = True

SELECTABLE_DOMAINS = [
    "light",
    "switch",
    "cover",
    "climate",
    "fan",
    "media_player",
    "scene",
    "script",
    "lock",
    "vacuum",
    "valve",
    "water_heater",
    "humidifier",
    "weather",
    "sensor",
    "binary_sensor",
    "input_boolean",
]

# The sidecar's own hard timeout is 20 s and it reports that as an `error: timeout` event. The read
# timeout here only has to catch a sidecar that stops talking altogether.
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 25

UNREACHABLE_MESSAGE = "Claude ist gerade nicht erreichbar."
