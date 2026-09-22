"""Shared fixtures: a bed in range, and a Bluetooth client that plays one."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import octo_bed_protocol as protocol
import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octo_bed.const import (
    ADVERTISED_SERVICE_UUID,
    CONF_FEATURES,
    CONF_IDLE_TIMEOUT,
    CONF_MOVE_STEPS,
    CONF_PIN,
    CONF_POSITION_STEPS,
    CONF_STEP_INTERVAL,
    DOMAIN,
    SERVICE_UUID,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
PIN = "1234"

FEATURES = {
    "motor_count": 2,
    "memory_count": 2,
    "memory_kinds": [4, 2],
    "has_light": True,
    "light_on": False,
    "pin_set": True,
}

# Short enough that a whole movement fits into a test.
FAST = {
    CONF_STEP_INTERVAL: 100,
    CONF_MOVE_STEPS: 3,
    CONF_POSITION_STEPS: 4,
    CONF_IDLE_TIMEOUT: 1,
}


def feature_record(feature: int, value: bytes) -> bytes:
    """One entry of the feature listing, as the receiver sends it."""
    record = feature.to_bytes(3, "big") + bytes((1, 1, 1, 1)) + value
    return protocol.build_frame(b"\x21\x71", record)


LISTING = (
    feature_record(0x000001, b"\x02")
    + feature_record(0x000002, b"\x02")
    + feature_record(0x000003, b"\x01\x00")
    + feature_record(0x000102, b"\x00")
    + feature_record(0xFFFFFF, b"")
)
PIN_OK = protocol.build_frame(b"\x21\x43", b"\x01")
PIN_WRONG = protocol.build_frame(b"\x21\x43", b"\x00")
PIN_LOCK = protocol.build_frame(b"\x21\x44", b"")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make the custom integration loadable in every test."""


@pytest.fixture
async def bluetooth_ready(hass, mock_bluetooth: None) -> None:
    """Bring the bluetooth integration up, which the coordinator needs."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "bluetooth", {})
    await hass.async_block_till_done()


def make_service_info(
    address: str = ADDRESS,
    name: str = "RC2",
    uuids: list[str] | None = None,
) -> BluetoothServiceInfoBleak:
    """An advertisement as an RC2 receiver sends it."""
    device = MagicMock()
    device.address = address
    device.name = name
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=uuids
        if uuids is not None
        else [ADVERTISED_SERVICE_UUID, SERVICE_UUID],
        source="local",
        device=device,
        advertisement=MagicMock(),
        connectable=True,
        time=0,
        tx_power=-127,
    )


@pytest.fixture
def service_info() -> BluetoothServiceInfoBleak:
    """The bed's advertisement."""
    return make_service_info()


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A bed that is already set up."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Bed",
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_PIN: PIN, CONF_FEATURES: dict(FEATURES)},
        options=dict(FAST),
    )


class FakeBed:
    """A BleakClient stand-in that answers like a receiver.

    Every frame written is recorded. Answers go back through the notification
    callback the code under test subscribed with, the way the real one does.
    """

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.notify: Callable[[Any, bytearray], None] | None = None
        self.replies: dict[bytes, bytes] = {
            protocol.request_features(): LISTING,
            protocol.pin(PIN): PIN_OK,
        }
        self.disconnected_callback: Callable[[Any], None] | None = None
        self.client = AsyncMock()
        self.client.start_notify.side_effect = self._start_notify
        self.client.write_gatt_char.side_effect = self._write
        self.client.disconnect.return_value = None
        self.connects = 0

    async def _start_notify(self, _: str, callback: Callable[..., None]) -> None:
        self.notify = callback

    async def _write(self, _: str, frame: bytes, *args: Any) -> None:
        self.written.append(bytes(frame))
        if (reply := self.replies.get(bytes(frame))) and self.notify:
            # Split, because the real receiver does not send whole frames.
            self.notify(None, bytearray(reply[:3]))
            self.notify(None, bytearray(reply[3:]))

    def send(self, frame: bytes) -> None:
        """Push a notification the bed sends on its own."""
        assert self.notify is not None
        self.notify(None, bytearray(frame))

    async def connect(self, *args: Any, **kwargs: Any) -> AsyncMock:
        self.connects += 1
        self.disconnected_callback = kwargs.get("disconnected_callback")
        return self.client

    def frames(self, frame: bytes) -> int:
        return self.written.count(frame)


@pytest.fixture
def bed() -> Generator[FakeBed]:
    """A reachable bed with one connection path and free slots."""
    fake = FakeBed()
    allocations = MagicMock(slots=3, free=2)
    path = MagicMock()
    path.scanner.name = "proxy"
    path.scanner.get_allocations.return_value = allocations
    path.advertisement.rssi = -70
    with (
        patch(
            "custom_components.octo_bed.coordinator.establish_connection",
            side_effect=fake.connect,
        ),
        patch(
            "custom_components.octo_bed.coordinator.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(address=ADDRESS),
        ),
        patch(
            "custom_components.octo_bed.coordinator.bluetooth.async_scanner_devices_by_address",
            return_value=[path],
        ),
    ):
        fake.path = path  # type: ignore[attr-defined]
        yield fake


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip the actual setup while testing the flow."""
    with patch(
        "custom_components.octo_bed.async_setup_entry", return_value=True
    ) as mocked:
        yield mocked
