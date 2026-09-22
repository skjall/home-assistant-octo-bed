"""Wire protocol of Octo adjustable bed controllers.

This package knows how to build and read the bytes; it opens no connections
and depends on no Bluetooth stack, so it can be tested without hardware.
"""

from .const import (
    ADVERTISED_SERVICE_UUID,
    CHAR_UUID,
    MANUFACTURER,
    MOTOR_3,
    MOTOR_4,
    MOTOR_BITS,
    MOTOR_FEET,
    MOTOR_HEAD,
    NAME_PREFIXES,
    REPLY_PIN_LOCK,
    SERVICE_UUID,
)
from .protocol import (
    Features,
    FrameReader,
    Packet,
    build_frame,
    checksum,
    move,
    pin,
    pin_accepted,
    read_listing,
    recall_memory,
    request_features,
    set_light,
    stop,
)

__all__ = [
    "ADVERTISED_SERVICE_UUID",
    "CHAR_UUID",
    "MANUFACTURER",
    "MOTOR_3",
    "MOTOR_4",
    "MOTOR_BITS",
    "MOTOR_FEET",
    "MOTOR_HEAD",
    "NAME_PREFIXES",
    "REPLY_PIN_LOCK",
    "SERVICE_UUID",
    "Features",
    "FrameReader",
    "Packet",
    "build_frame",
    "checksum",
    "move",
    "pin",
    "pin_accepted",
    "read_listing",
    "recall_memory",
    "request_features",
    "set_light",
    "stop",
]
