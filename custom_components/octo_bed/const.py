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
    "CONF_DOWN_TIME",
    "CONF_FEATURES",
    "CONF_IDLE_TIMEOUT",
    "CONF_LISTING",
    "CONF_PIN",
    "CONF_POSITION_TIME",
    "CONF_STEP_INTERVAL",
    "CONF_UP_TIME",
    "DEFAULTS",
    "DOMAIN",
    "KEEPALIVE_INTERVAL",
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
# The notifications that listing arrived in, as hex, for the diagnostics.
CONF_LISTING: Final = "listing"

# How a movement is driven. The receiver runs a motor only while the command
# keeps arriving, so a movement is a step every STEP_INTERVAL for as long as
# its run time lasts, followed by a stop. Run times are in seconds, per
# direction; the number of steps follows from them.
CONF_STEP_INTERVAL: Final = "step_interval"
CONF_UP_TIME: Final = "up_time"
CONF_DOWN_TIME: Final = "down_time"
CONF_POSITION_TIME: Final = "position_time"
# How long a connection is kept open after the last command. The proxy has only
# a handful of connection slots, and a bed that holds one keeps it from every
# other device.
CONF_IDLE_TIMEOUT: Final = "idle_timeout"

# How often the PIN is repeated while a connection is open. A locked receiver
# drops the link after about 30 seconds without it.
KEEPALIVE_INTERVAL: Final = 25.0

# The vendor app repeats a held button every 300 to 350 ms, and the ESPHome
# setup this replaces ran 50 steps at 300 ms: 15 seconds.
DEFAULTS: Final[dict[str, float]] = {
    CONF_STEP_INTERVAL: 300,
    CONF_UP_TIME: 15,
    CONF_DOWN_TIME: 15,
    CONF_POSITION_TIME: 30,
    CONF_IDLE_TIMEOUT: 10,
}
