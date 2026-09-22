"""The wire format, checked against frames the vendor app was seen to send."""

import pytest
from octo_bed_protocol import (
    MOTOR_3,
    MOTOR_4,
    MOTOR_FEET,
    MOTOR_HEAD,
    Features,
    FrameReader,
    Packet,
    build_frame,
    move,
    pin,
    pin_accepted,
    read_listing,
    recall_memory,
    request_features,
    set_light,
    stop,
)

BOTH = MOTOR_HEAD | MOTOR_FEET


def frame(text: str) -> bytes:
    return bytes.fromhex(text)


# Captured from the vendor app, and sent by the ESPHome setup this package
# replaces for months without complaint.
@pytest.mark.parametrize(
    ("motors", "up", "captured"),
    [
        (MOTOR_HEAD, True, "40 02 70 00 01 0b 02 40"),
        (MOTOR_HEAD, False, "40 02 71 00 01 0a 02 40"),
        (MOTOR_FEET, True, "40 02 70 00 01 09 04 40"),
        (MOTOR_FEET, False, "40 02 71 00 01 08 04 40"),
        (BOTH, True, "40 02 70 00 01 07 06 40"),
        (BOTH, False, "40 02 71 00 01 06 06 40"),
    ],
)
def test_move_matches_the_capture(motors: int, up: bool, captured: str) -> None:
    assert move(motors, up) == frame(captured)


def test_stop_matches_the_capture() -> None:
    assert stop() == frame("40 02 73 00 00 0b 40")


def test_light_matches_the_capture() -> None:
    assert set_light(True) == frame("40 20 72 00 08 de 00 01 02 01 01 01 01 01 40")
    assert set_light(False) == frame("40 20 72 00 08 df 00 01 02 01 01 01 01 00 40")


def test_pin_is_four_raw_digits() -> None:
    assert pin("2345") == frame("40 20 43 00 04 0b 02 03 04 05 40")


@pytest.mark.parametrize("digits", ["123", "12345", "12a4", ""])
def test_pin_rejects_anything_but_four_digits(digits: str) -> None:
    with pytest.raises(ValueError):
        pin(digits)


def test_every_frame_sums_to_zero() -> None:
    for built in (
        move(MOTOR_3 | MOTOR_4, True),
        recall_memory(2),
        request_features(),
        pin("9999"),
    ):
        assert sum(built) & 0xFF == 0


def test_feature_request() -> None:
    assert request_features() == frame("40 20 71 00 00 ef 40")


def test_memory_recall() -> None:
    assert recall_memory(0) == frame("40 02 72 00 01 0b 00 40")
    with pytest.raises(ValueError):
        recall_memory(256)


@pytest.mark.parametrize("mask", [0, 0x01, 0x20, 0x06 | 0x40])
def test_move_rejects_what_is_not_a_motor(mask: int) -> None:
    with pytest.raises(ValueError):
        move(mask, True)


def test_build_frame_wants_a_two_byte_command() -> None:
    with pytest.raises(ValueError):
        build_frame(b"\x02")


def test_framing_bytes_in_the_payload_are_escaped() -> None:
    built = build_frame(b"\x02\x70", bytes((0x40, 0x3C, 0x4F, 0x41)))
    inner = built[1:-1]
    assert 0x40 not in inner
    assert bytes((0x3C, 0x01)) in inner
    # And a reader takes it apart again.
    [packet] = FrameReader().feed(built)
    assert packet.data == bytes((0x40, 0x3C, 0x4F, 0x41))


def _feature(feature: int, value: bytes, characteristic: bytes = b"\x01") -> bytes:
    record = (
        feature.to_bytes(3, "big")
        + bytes((1, len(characteristic)))
        + characteristic
        + b"\x01"
        + value
    )
    return build_frame(b"\x21\x71", record)


def test_reader_reassembles_split_and_joined_frames() -> None:
    reader = FrameReader()
    first = _feature(0x000001, b"\x02")
    second = _feature(0x000102, b"\x01")
    assert reader.feed(first[:4]) == []
    packets = reader.feed(first[4:] + second)
    assert [p.command for p in packets] == [b"\x21\x71", b"\x21\x71"]


def test_reader_drops_what_does_not_add_up() -> None:
    reader = FrameReader()
    good = _feature(0x000001, b"\x02")
    bad_checksum = bytearray(good)
    bad_checksum[5] ^= 0xFF
    bad_length = bytearray(good)
    bad_length[4] += 1
    bad_escape = bytes((0x40, 0x21, 0x71, 0x3C, 0x09, 0x40))
    packets = reader.feed(
        b"noise" + bytes(bad_checksum) + bytes(bad_length) + bad_escape + good
    )
    assert len(packets) == 1


def test_reader_forgets_a_frame_that_never_ends() -> None:
    reader = FrameReader()
    assert reader.feed(bytes((0x40,)) + bytes(300)) == []
    assert reader.feed(stop()) == [Packet(command=b"\x02\x73", data=b"")]


def test_reader_without_any_delimiter() -> None:
    assert FrameReader().feed(b"\x01\x02") == []


def test_features_from_a_full_listing() -> None:
    reader = FrameReader()
    features = Features()
    listing = (
        _feature(0x000001, b"\x02")
        + _feature(0x000002, b"\x04")
        + _feature(0x000004, b"\x01\x02\x03\x04", characteristic=b"\x04\x00\x00")
        + _feature(0x000003, b"\x01\x01")
        + _feature(0x000101, b"")
        + _feature(0x000102, b"\x01")
        + _feature(0xFFFFFF, b"")
    )
    for packet in reader.feed(listing):
        features.add(packet)
    assert features.complete
    assert features.motor_count == 2
    assert features.motor_mask() == BOTH
    assert features.memory_count == 4
    assert features.memory_kinds == [1, 2, 3, 4]
    assert features.pin_set
    assert features.pin_unlocked
    assert features.has_light
    assert features.light_on


def test_features_ignore_other_frames() -> None:
    features = Features()
    features.add(Packet(command=b"\x21\x43", data=b"\x01"))
    features.add(Packet(command=b"\x21\x71", data=b"\x00"))
    assert features == Features()


def test_locked_pin_and_no_light() -> None:
    features = Features()
    [packet] = FrameReader().feed(_feature(0x000003, b"\x01\x00"))
    features.add(packet)
    assert features.pin_set
    assert not features.pin_unlocked
    assert not features.has_light
    assert features.motor_mask() == 0


def test_pin_state_reply() -> None:
    assert pin_accepted(Packet(command=b"\x21\x43", data=b"\x01")) is True
    assert pin_accepted(Packet(command=b"\x21\x43", data=b"\x00")) is False
    assert pin_accepted(Packet(command=b"\x21\x43", data=b"")) is False
    assert pin_accepted(Packet(command=b"\x21\x71", data=b"\x01")) is None


def _unescaped(command: bytes, data: bytes) -> bytes:
    """A frame the way the RC2 sends its replies: no escaping at all."""
    body = bytearray(command) + len(data).to_bytes(2, "big") + b"\x00" + data
    body[4] = (-(0x80 + sum(body))) & 0xFF
    return bytes((0x40, *body, 0x40))


def test_an_unescaped_delimiter_in_the_data_is_data() -> None:
    record = bytes.fromhex("00 00 01 01 01 40 01 02")
    frame = _unescaped(b"\x21\x71", record)
    [packet] = FrameReader().feed(frame)
    assert packet.data == record


def test_an_unescaped_delimiter_as_checksum() -> None:
    reader = FrameReader()
    # Search a record whose checksum comes out as 0x40.
    for value in range(256):
        frame = _unescaped(b"\x21\x71", bytes((0, 0, 1, 1, 1, 1, 1, value)))
        if frame[5] == 0x40:
            break
    else:  # pragma: no cover
        raise AssertionError("no such record")
    features = Features()
    for packet in reader.feed(
        frame + _unescaped(b"\x21\x71", bytes.fromhex("ff ff ff 00 00 00"))
    ):
        features.add(packet)
    assert features.motor_count == value
    assert features.complete


def test_a_frame_split_before_its_length_is_known() -> None:
    reader = FrameReader()
    frame = _unescaped(b"\x21\x71", bytes.fromhex("00 00 01 01 01 01 01 02"))
    assert reader.feed(frame[:3]) == []
    assert reader.feed(frame[3:9]) == []
    assert len(reader.feed(frame[9:])) == 1


# The listing both RC2 receivers here sent, notification by notification.
RC2_LISTING = [
    bytes.fromhex("40 21 71 00 07 e2 00 00 01 01 01 02 00 40"),
    bytes.fromhex("40 21 71 00 08 df 00 01 02 01 01 01 01 00 40"),
    bytes.fromhex("40 21 71 00 08 d2 00 00 10 01 01 01 01 00 40"),
    bytes.fromhex("40 21 71 00 06 ea ff ff ff 01 00 00 40"),
]


def test_the_rc2_listing() -> None:
    """Two motors in the characteristic, a light that is off, no PIN."""
    features = read_listing(RC2_LISTING)
    assert features.complete
    assert features.motor_count == 2
    assert features.motor_mask() == MOTOR_HEAD | MOTOR_FEET
    assert features.has_light
    assert not features.light_on
    assert not features.pin_set
    assert features.memory_count == 0


def test_a_motor_count_without_any_bytes() -> None:
    frame = build_frame(b"\x21\x71", bytes.fromhex("00 00 01 01 00 00"))
    assert read_listing([frame]).motor_count is None
