"""Constants of the Home Assistant integration.

Everything about the device itself - UUIDs, command words, motor bits - lives
in the octo_bed_protocol package and is re-exported here, so the platforms have
one place to import from.
"""

from typing import Final

from octo_bed_protocol import (
    ADVERTISED_SERVICE_UUID,
    CHAR_UUID,
    MANUFACTURER,
    MOTOR_3,
    MOTOR_4,
    MOTOR_FEET,
    MOTOR_HEAD,
    NAME_PREFIXES,
    SERVICE_UUID,
)

__all__ = [
    "ADVERTISED_SERVICE_UUID",
    "CHAR_UUID",
    "CONF_FEATURES",
    "CONF_IDLE_TIMEOUT",
    "CONF_KEEPALIVE_INTERVAL",
    "CONF_MOVE_STEPS",
    "CONF_PIN",
    "CONF_POSITION_STEPS",
    "CONF_STEP_INTERVAL",
    "DEFAULTS",
    "DOMAIN",
    "LIMITS",
    "MANUFACTURER",
    "MOTOR_3",
    "MOTOR_4",
    "MOTOR_FEET",
    "MOTOR_HEAD",
    "NAME_PREFIXES",
    "SERVICE_UUID",
]

DOMAIN: Final = "octo_bed"

CONF_PIN: Final = "pin"
# What the receiver said about itself during setup: motors, memories, light.
CONF_FEATURES: Final = "features"

# How a movement is driven. The receiver runs a motor only while the command
# keeps arriving, so a movement is a number of steps at a fixed interval,
# followed by a stop.
CONF_STEP_INTERVAL: Final = "step_interval"
CONF_MOVE_STEPS: Final = "move_steps"
CONF_POSITION_STEPS: Final = "position_steps"
# How long a connection is kept open after the last command. The proxy has only
# a handful of connection slots, and a bed that holds one keeps it from every
# other device.
CONF_IDLE_TIMEOUT: Final = "idle_timeout"
# How often the PIN is repeated while a connection is open. A locked receiver
# drops the link after about 30 seconds without it.
CONF_KEEPALIVE_INTERVAL: Final = "keepalive_interval"

# The vendor app repeats a held button every 300 to 350 ms, and the ESPHome
# setup this replaces ran 50 steps at 300 ms.
DEFAULTS: Final[dict[str, int]] = {
    CONF_STEP_INTERVAL: 300,
    CONF_MOVE_STEPS: 50,
    CONF_POSITION_STEPS: 100,
    CONF_IDLE_TIMEOUT: 10,
    CONF_KEEPALIVE_INTERVAL: 25,
}

LIMITS: Final[dict[str, tuple[int, int, int]]] = {
    # minimum, maximum, step
    CONF_STEP_INTERVAL: (100, 1000, 10),
    CONF_MOVE_STEPS: (1, 1000, 1),
    CONF_POSITION_STEPS: (1, 1000, 1),
    CONF_IDLE_TIMEOUT: (1, 300, 1),
    CONF_KEEPALIVE_INTERVAL: (5, 28, 1),
}
