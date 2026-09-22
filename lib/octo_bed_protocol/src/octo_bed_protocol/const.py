"""Identifiers and command words of Octo bed controllers."""

from typing import Final

MANUFACTURER: Final = "Octo"

# Every frame travels over this one characteristic, in both directions: writes
# carry commands, notifications carry the answers.
SERVICE_UUID: Final = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID: Final = "0000ffe1-0000-1000-8000-00805f9b34fb"

# Advertised next to FFE0 by the RC2 receivers this was verified against.
# FFE0 alone is shared with several other bed families, and the local name is
# not reliable either: one of the two receivers advertised garbage instead of
# "RC2". This UUID is what both had in common.
ADVERTISED_SERVICE_UUID: Final = "58debc00-4083-4735-8926-6721a778ae5e"

# Names the vendor app lists for Octo receivers, matched as prefixes.
NAME_PREFIXES: Final = (
    "RC2",
    "RC3",
    "MC1",
    "MC2",
    "RTV",
    "L2M",
    "CLI",
    "BMB",
    "BMS",
    "BM3",
    "OCTOBRICK",
    "OCTOIQ",
)

FRAME_DELIMITER: Final = 0x40

# Commands to the receiver. A reply sets bit 0 of the first byte.
CMD_MOVE_UP: Final = b"\x02\x70"
CMD_MOVE_DOWN: Final = b"\x02\x71"
CMD_MEMORY_RECALL: Final = b"\x02\x72"
CMD_STOP: Final = b"\x02\x73"
CMD_PIN: Final = b"\x20\x43"
CMD_FEATURES: Final = b"\x20\x71"
CMD_SET_FEATURE: Final = b"\x20\x72"

# Notifications from the receiver.
REPLY_PIN_STATE: Final = b"\x21\x43"
REPLY_PIN_LOCK: Final = b"\x21\x44"
REPLY_FEATURE: Final = b"\x21\x71"

# Motor bits of the move command. M1 lifts the back, M2 the legs.
MOTOR_HEAD: Final = 0x02
MOTOR_FEET: Final = 0x04
MOTOR_3: Final = 0x08
MOTOR_4: Final = 0x10
MOTOR_BITS: Final = (MOTOR_HEAD, MOTOR_FEET, MOTOR_3, MOTOR_4)

# Feature ids the receiver lists in answer to CMD_FEATURES.
FEATURE_MOTOR_COUNT: Final = 0x000001
FEATURE_MEMORY_COUNT: Final = 0x000002
FEATURE_PIN: Final = 0x000003
FEATURE_MEMORY_INFO: Final = 0x000004
FEATURE_LIGHT: Final = 0x000102
FEATURE_END: Final = 0xFFFFFF
