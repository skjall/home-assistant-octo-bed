"""The wire format: building frames, and reading what the receiver sends back.

A frame is ``40 | command (2) | data length (2, big-endian) | checksum | data |
40``. The checksum makes the byte sum of the whole frame, both delimiters
included, come out as zero.

Between the delimiters the vendor app escapes the four bytes that would
otherwise be taken for framing. None of the commands this package builds
happens to contain one, which is why the escape never showed up in a capture.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import (
    CMD_FEATURES,
    CMD_MEMORY_RECALL,
    CMD_MOVE_DOWN,
    CMD_MOVE_UP,
    CMD_PIN,
    CMD_SET_FEATURE,
    CMD_STOP,
    FEATURE_END,
    FEATURE_LIGHT,
    FEATURE_MEMORY_COUNT,
    FEATURE_MEMORY_INFO,
    FEATURE_MOTOR_COUNT,
    FEATURE_PIN,
    FRAME_DELIMITER,
    MOTOR_BITS,
    REPLY_FEATURE,
    REPLY_PIN_STATE,
)

_ESCAPE = 0x3C
_ESCAPED = {0x40: 0x01, 0x3C: 0x02, 0x4F: 0x03, 0x41: 0x04}
_UNESCAPED = {value: key for key, value in _ESCAPED.items()}

# Longest frame that is still believable. A buffer that grows past this without
# a closing delimiter is noise, not a frame that is still arriving.
_MAX_FRAME = 256


def checksum(frame: bytes) -> int:
    """Return the byte that makes the frame sum to zero.

    The checksum position itself is expected to hold zero while summing.
    """
    return (-sum(frame)) & 0xFF


def _escape(payload: bytes) -> bytes:
    out = bytearray()
    for byte in payload:
        if byte in _ESCAPED:
            out += bytes((_ESCAPE, _ESCAPED[byte]))
        else:
            out.append(byte)
    return bytes(out)


def _unescape(payload: bytes) -> bytes | None:
    out = bytearray()
    it = iter(payload)
    for byte in it:
        if byte != _ESCAPE:
            out.append(byte)
            continue
        code = next(it, None)
        if code not in _UNESCAPED:
            return None
        out.append(_UNESCAPED[code])
    return bytes(out)


def build_frame(command: bytes, data: bytes = b"") -> bytes:
    """Wrap one command and its data into a frame."""
    if len(command) != 2:
        raise ValueError("a command is two bytes")
    body = bytearray(command)
    body += len(data).to_bytes(2, "big")
    body.append(0)
    body += data
    body[4] = checksum(bytes((FRAME_DELIMITER, *body, FRAME_DELIMITER)))
    return bytes((FRAME_DELIMITER, *_escape(bytes(body)), FRAME_DELIMITER))


def move(motors: int, up: bool) -> bytes:
    """Run the given motors one step; the receiver stops unless it is repeated."""
    if not motors or motors & ~sum(MOTOR_BITS):
        raise ValueError(f"not a motor mask: {motors:#x}")
    return build_frame(CMD_MOVE_UP if up else CMD_MOVE_DOWN, bytes((motors,)))


def stop() -> bytes:
    """Stop every motor."""
    return build_frame(CMD_STOP)


def recall_memory(slot: int) -> bytes:
    """Drive one step towards a stored position (slot counted from zero)."""
    if not 0 <= slot <= 0xFF:
        raise ValueError(f"not a memory slot: {slot}")
    return build_frame(CMD_MEMORY_RECALL, bytes((slot,)))


def pin(digits: str) -> bytes:
    """Unlock the receiver: four digits, one raw byte each."""
    if len(digits) != 4 or not digits.isdigit():
        raise ValueError("the PIN is four digits")
    return build_frame(CMD_PIN, bytes(int(c) for c in digits))


def request_features() -> bytes:
    """Ask the receiver which motors, memories and light it has."""
    return build_frame(CMD_FEATURES)


def set_light(on: bool) -> bytes:
    """Switch the under-bed light.

    A feature record: id 0x000102, flag, one characteristic byte, value type,
    then the value. Byte for byte what the vendor app sends.
    """
    record = FEATURE_LIGHT.to_bytes(3, "big") + bytes((1, 1, 1, 1, int(on)))
    return build_frame(CMD_SET_FEATURE, record)


@dataclass(frozen=True)
class Packet:
    """One frame received from the bed, already checked."""

    command: bytes
    data: bytes


class FrameReader:
    """Reassemble frames from notifications.

    A frame may be split across notifications, and one notification may carry
    several frames. Anything that does not add up - a bad checksum, a length
    that does not match - is dropped rather than guessed at.
    """

    def __init__(self) -> None:
        """Start with nothing buffered."""
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[Packet]:
        """Take one notification, return every frame it completed."""
        self._buffer += chunk
        packets: list[Packet] = []
        while True:
            start = self._buffer.find(FRAME_DELIMITER)
            if start < 0:
                self._buffer.clear()
                return packets
            del self._buffer[:start]
            end = self._buffer.find(FRAME_DELIMITER, 1)
            if end < 0:
                if len(self._buffer) > _MAX_FRAME:
                    self._buffer.clear()
                return packets
            raw = bytes(self._buffer[1:end])
            del self._buffer[: end + 1]
            if not raw:
                # Two delimiters back to back: the second one opens the next
                # frame, the first one closed nothing.
                self._buffer[:0] = bytes((FRAME_DELIMITER,))
                continue
            if (packet := _decode(raw)) is not None:
                packets.append(packet)


def _decode(raw: bytes) -> Packet | None:
    body = _unescape(raw)
    if body is None or len(body) < 5:
        return None
    length = int.from_bytes(body[2:4], "big")
    if len(body) != 5 + length:
        return None
    if sum((FRAME_DELIMITER, *body, FRAME_DELIMITER)) & 0xFF:
        return None
    return Packet(command=body[:2], data=body[5:])


def pin_accepted(packet: Packet) -> bool | None:
    """Return whether a PIN state reply says unlocked, or None for other frames."""
    if packet.command != REPLY_PIN_STATE:
        return None
    return bool(packet.data) and packet.data[0] == 1


@dataclass
class Features:
    """What the receiver says about itself, one record at a time."""

    motor_count: int | None = None
    memory_count: int = 0
    memory_kinds: list[int] = field(default_factory=list)
    has_light: bool = False
    light_on: bool = False
    pin_set: bool = False
    pin_unlocked: bool = True
    complete: bool = False

    def add(self, packet: Packet) -> None:
        """Take one feature record into account."""
        if packet.command != REPLY_FEATURE or len(packet.data) < 5:
            return
        data = packet.data
        feature = int.from_bytes(data[0:3], "big")
        # A flag, then a length-prefixed characteristic, then one byte of value
        # type, then the value. Only the value matters for what is read here.
        value = data[6 + data[4] :]
        if feature == FEATURE_END:
            self.complete = True
        elif feature == FEATURE_MOTOR_COUNT and value:
            self.motor_count = value[0]
        elif feature == FEATURE_MEMORY_COUNT and value:
            self.memory_count = value[0]
        elif feature == FEATURE_MEMORY_INFO:
            self.memory_kinds = list(value)
        elif feature == FEATURE_PIN and value:
            self.pin_set = value[0] == 1
            self.pin_unlocked = len(value) < 2 or value[1] == 1
        elif feature == FEATURE_LIGHT:
            self.has_light = True
            self.light_on = bool(value) and value[0] == 1

    def motor_mask(self) -> int:
        """Return the bits of every motor the receiver drives."""
        count = min(self.motor_count or 0, len(MOTOR_BITS))
        return sum(MOTOR_BITS[:count])
