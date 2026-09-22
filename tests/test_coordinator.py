"""The coordinator: when it connects, what it sends, and when it hangs up."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from unittest.mock import MagicMock, patch

import octo_bed_protocol as protocol
import pytest
from bleak.exc import BleakError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octo_bed.const import MOTOR_FEET, MOTOR_HEAD
from custom_components.octo_bed.coordinator import (
    OctoBedCoordinator,
    PinRejectedError,
    Timings,
    async_probe,
    check_free_slot,
    features_from_data,
)

from .conftest import (
    ADDRESS,
    FAST,
    FEATURES,
    PIN,
    PIN_LOCK,
    PIN_WRONG,
    FakeBed,
    feature_record,
)

BOTH = MOTOR_HEAD | MOTOR_FEET
MODULE = "custom_components.octo_bed.coordinator"


def make(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    pin: str | None = PIN,
    **timings: float,
) -> OctoBedCoordinator:
    base = Timings.from_options(FAST)
    return OctoBedCoordinator(
        hass,
        entry,
        ADDRESS,
        pin,
        features_from_data(FEATURES),
        Timings(**{**base.__dict__, "step_interval": 0.01, **timings}),
    )


@pytest.fixture
async def factory(
    hass: HomeAssistant, bluetooth_ready: None, mock_config_entry: MockConfigEntry
) -> AsyncGenerator[Callable[..., OctoBedCoordinator]]:
    """Build coordinators, and hang every one of them up afterwards."""
    mock_config_entry.add_to_hass(hass)
    built: list[OctoBedCoordinator] = []

    def build(pin: str | None = PIN, **timings: float) -> OctoBedCoordinator:
        built.append(make(hass, mock_config_entry, pin, **timings))
        return built[-1]

    yield build
    for coordinator in built:
        await coordinator.async_shutdown()


@pytest.fixture
def coordinator(factory: Callable[..., OctoBedCoordinator]) -> OctoBedCoordinator:
    return factory()


async def _settle(coordinator: OctoBedCoordinator) -> None:
    """Wait for a running movement to finish."""
    for _ in range(200):
        if coordinator.motion is None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the movement never ended")  # pragma: no cover


async def test_a_movement_runs_its_steps_then_stops(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """Three steps, then a stop, over one connection that was unlocked first."""
    await coordinator.async_move(MOTOR_HEAD, True)
    assert coordinator.connected
    assert coordinator.motion is not None and coordinator.motion.up is True
    await _settle(coordinator)

    assert bed.written[0] == protocol.pin(PIN)
    assert bed.frames(protocol.move(MOTOR_HEAD, True)) == 3
    assert bed.written[-1] == protocol.stop()
    assert bed.connects == 1


async def test_the_connection_is_closed_when_left_alone(
    hass: HomeAssistant, factory, bed: FakeBed
) -> None:
    """No standing connection: the slot is given back after the idle timeout."""
    coordinator = factory(idle_timeout=0.05)
    await coordinator.async_move(MOTOR_FEET, False)
    await _settle(coordinator)
    assert coordinator.connected

    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    assert not coordinator.connected
    bed.client.disconnect.assert_awaited()


async def test_a_second_command_reuses_the_connection(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """Within the idle timeout nothing reconnects."""
    await coordinator.async_move(MOTOR_HEAD, True)
    await _settle(coordinator)
    await coordinator.async_set_light(True)
    assert bed.connects == 1
    assert coordinator.light_on
    assert bed.written[-1] == protocol.set_light(True)


async def test_a_new_movement_replaces_the_running_one(
    hass: HomeAssistant, factory, bed: FakeBed
) -> None:
    """Opposite directions never run at the same time."""
    coordinator = factory(move_steps=50)
    await coordinator.async_move(MOTOR_HEAD, True)
    await coordinator.async_move(MOTOR_HEAD, False)
    assert coordinator.motion is not None and coordinator.motion.up is False
    await coordinator.async_stop()
    assert coordinator.motion is None
    assert bed.written[-1] == protocol.stop()


async def test_stop_without_a_connection_sends_nothing(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """Nothing moves without a connection, so there is no reason to open one."""
    await coordinator.async_stop()
    assert bed.connects == 0
    assert bed.written == []


async def test_flat_and_memory_run_the_position_steps(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """Both are held for the longer number of steps."""
    await coordinator.async_flat()
    await _settle(coordinator)
    assert bed.frames(protocol.move(BOTH, False)) == 4

    await coordinator.async_recall_memory(1)
    assert coordinator.motion is not None and coordinator.motion.memory == 1
    await _settle(coordinator)
    assert bed.frames(protocol.recall_memory(1)) == 4


async def test_no_pin_is_sent_to_a_bed_without_one(
    hass: HomeAssistant, factory, bed: FakeBed
) -> None:
    """A PIN is only sent where the receiver said one is set."""
    coordinator = factory(pin=None)
    await coordinator.async_set_light(False)
    assert bed.written == [protocol.set_light(False)]


async def test_a_rejected_pin_asks_for_a_new_one(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """The action fails, the connection is dropped, and reauth starts."""
    bed.replies[protocol.pin(PIN)] = PIN_WRONG
    with (
        patch.object(coordinator.entry, "async_start_reauth") as reauth,
        pytest.raises(HomeAssistantError) as raised,
    ):
        await coordinator.async_move(MOTOR_HEAD, True)
    assert raised.value.translation_key == "invalid_pin"
    reauth.assert_called_once()
    assert not coordinator.connected
    bed.client.disconnect.assert_awaited()


async def test_a_pin_without_an_answer_is_taken_as_given(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """Some receivers stay silent; the command goes out regardless."""
    del bed.replies[protocol.pin(PIN)]
    with patch(f"{MODULE}._PIN_REPLY_TIMEOUT", 0.01):
        await coordinator.async_set_light(True)
    assert bed.written[-1] == protocol.set_light(True)


async def test_the_pin_is_repeated_while_connected(
    hass: HomeAssistant, factory, bed: FakeBed
) -> None:
    """A keepalive, and an answer when the receiver locks itself."""
    coordinator = factory(keepalive_interval=0.02)
    await coordinator.async_set_light(True)
    await asyncio.sleep(0.07)
    assert bed.frames(protocol.pin(PIN)) >= 3

    before = bed.frames(protocol.pin(PIN))
    bed.send(PIN_LOCK)
    await hass.async_block_till_done()
    assert bed.frames(protocol.pin(PIN)) > before

    # An unsolicited rejection is only logged.
    bed.send(PIN_WRONG)
    await coordinator.async_disconnect()


async def test_the_keepalive_ends_with_the_link(
    hass: HomeAssistant, factory, bed: FakeBed
) -> None:
    """A write that fails ends the keepalive instead of spinning."""
    coordinator = factory(keepalive_interval=0.02)
    await coordinator.async_set_light(True)
    bed.client.write_gatt_char.side_effect = BleakError("gone")
    await asyncio.sleep(0.05)
    assert coordinator._keepalive_task is not None
    assert coordinator._keepalive_task.done()
    await coordinator.async_disconnect()


async def test_the_bed_hanging_up_ends_everything(
    hass: HomeAssistant, factory, bed: FakeBed
) -> None:
    """A dropped link cancels the movement and the keepalive."""
    coordinator = factory(move_steps=100)
    await coordinator.async_move(MOTOR_HEAD, True)
    assert bed.disconnected_callback is not None

    # A callback from an older connection changes nothing.
    coordinator._on_disconnect(coordinator._generation - 1, bed.client)
    assert coordinator.connected

    bed.disconnected_callback(bed.client)
    await _settle(coordinator)
    assert not coordinator.connected
    assert coordinator._keepalive_task is None

    # And a second callback for the same link is harmless.
    bed.disconnected_callback(bed.client)


async def test_a_movement_that_breaks_off(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """A failing write mid-movement ends it without raising anywhere."""
    await coordinator.async_move(MOTOR_HEAD, True)
    bed.client.write_gatt_char.side_effect = BleakError("gone")
    await _settle(coordinator)
    assert coordinator.motion is None


async def test_a_failing_first_step_fails_the_action(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """The user hears about it, with the bed's name."""
    bed.client.write_gatt_char.side_effect = BleakError("nope")
    with pytest.raises(HomeAssistantError) as raised:
        await coordinator.async_move(MOTOR_HEAD, True)
    assert raised.value.translation_key == "command_failed"


async def test_a_connection_that_fails(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """Connecting fails as an action error, not as a crash."""
    with (
        patch(f"{MODULE}.establish_connection", side_effect=BleakError("nope")),
        pytest.raises(HomeAssistantError) as raised,
    ):
        await coordinator.async_set_light(True)
    assert raised.value.translation_key == "command_failed"
    assert not coordinator.connected


async def test_an_idle_timeout_does_not_cut_a_new_command_short(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """A hang-up decided before the latest command is dropped."""
    await coordinator.async_set_light(True)
    stale = coordinator._activity
    await coordinator.async_set_light(False)
    await coordinator._async_idle_disconnect(stale)
    assert coordinator.connected

    # The timer firing, without waiting the whole timeout for it.
    coordinator._cancel_idle()
    coordinator._idle_expired()
    await hass.async_block_till_done()
    assert not coordinator.connected


async def test_writing_without_a_connection(
    coordinator: OctoBedCoordinator,
) -> None:
    """A late keepalive after the link is gone fails like a lost link."""
    with pytest.raises(BleakError):
        await coordinator._async_write(protocol.stop())


async def test_disconnecting_twice_and_a_hang_up_that_hangs(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """Closing is best effort and never blocks."""
    await coordinator.async_disconnect()
    await coordinator.async_set_light(True)
    bed.client.disconnect.side_effect = BleakError("already gone")
    await coordinator.async_disconnect()
    assert not coordinator.connected


async def test_shutdown_stops_a_running_movement(
    hass: HomeAssistant, factory, bed: FakeBed
) -> None:
    """Unloading mid-movement stops the motors before hanging up."""
    coordinator = factory(move_steps=100)
    await coordinator.async_move(MOTOR_HEAD, True)
    await coordinator.async_shutdown()
    assert bed.written[-1] == protocol.stop()
    assert not coordinator.connected


async def test_available_while_connected(
    hass: HomeAssistant, coordinator: OctoBedCoordinator, bed: FakeBed
) -> None:
    """A connected bed stops advertising and is still there."""
    coordinator._available = False
    assert not coordinator.available
    await coordinator.async_set_light(True)
    assert coordinator.available


async def test_free_slots(hass: HomeAssistant, bed: FakeBed) -> None:
    """Out of slots only when every path that hears the bed is full."""
    check_free_slot(hass, ADDRESS)

    bed.path.scanner.get_allocations.return_value = MagicMock(slots=3, free=0)  # type: ignore[attr-defined]
    with pytest.raises(HomeAssistantError) as raised:
        check_free_slot(hass, ADDRESS)
    assert raised.value.translation_key == "no_free_slot"

    # An adapter that reports no slots at all is not taken for a full one.
    bed.path.scanner.get_allocations.return_value = None  # type: ignore[attr-defined]
    check_free_slot(hass, ADDRESS)

    with (
        patch(f"{MODULE}.bluetooth.async_scanner_devices_by_address", return_value=[]),
        pytest.raises(HomeAssistantError) as raised,
    ):
        check_free_slot(hass, ADDRESS)
    assert raised.value.translation_key == "not_in_range"


async def test_out_of_range(hass: HomeAssistant, bed: FakeBed) -> None:
    """No route to the bed says so."""
    with (
        patch(f"{MODULE}.bluetooth.async_ble_device_from_address", return_value=None),
        pytest.raises(HomeAssistantError) as raised,
    ):
        await async_probe(hass, ADDRESS, "Bed", None)
    assert raised.value.translation_key == "not_in_range"


async def test_probe_reads_the_features(hass: HomeAssistant, bed: FakeBed) -> None:
    """The setup flow learns motors, memories, light and the PIN."""
    features = await async_probe(hass, ADDRESS, "Bed", PIN)
    assert features.motor_count == 2
    assert features.memory_count == 2
    assert features.has_light
    assert features.pin_set
    assert bed.written == [protocol.request_features(), protocol.pin(PIN)]
    bed.client.disconnect.assert_awaited()


async def test_probe_without_a_pin(hass: HomeAssistant, bed: FakeBed) -> None:
    """Without a PIN only the features are asked for."""
    features = await async_probe(hass, ADDRESS, "Bed", None)
    assert features.pin_set
    assert bed.written == [protocol.request_features()]


async def test_probe_with_a_wrong_pin(hass: HomeAssistant, bed: FakeBed) -> None:
    """A rejected PIN is reported as such."""
    bed.replies[protocol.pin(PIN)] = PIN_WRONG
    with pytest.raises(PinRejectedError):
        await async_probe(hass, ADDRESS, "Bed", PIN)


async def test_probe_with_a_silent_pin(hass: HomeAssistant, bed: FakeBed) -> None:
    """No verdict on the PIN is taken as a yes."""
    del bed.replies[protocol.pin(PIN)]
    with patch(f"{MODULE}._PIN_REPLY_TIMEOUT", 0.01):
        await async_probe(hass, ADDRESS, "Bed", PIN)


async def test_probe_of_a_bed_that_never_finishes(
    hass: HomeAssistant, bed: FakeBed
) -> None:
    """A listing without its end marker times out."""
    bed.replies[protocol.request_features()] = feature_record(0x000001, b"\x02")
    with (
        patch(f"{MODULE}._FEATURE_TIMEOUT", 0.01),
        pytest.raises(TimeoutError),
    ):
        await async_probe(hass, ADDRESS, "Bed", None)
    bed.client.disconnect.assert_awaited()


async def test_a_hang_up_that_never_returns(hass: HomeAssistant, bed: FakeBed) -> None:
    """The deadline on disconnect holds."""

    async def forever() -> None:
        await asyncio.Event().wait()

    bed.client.disconnect.side_effect = forever
    with patch(f"{MODULE}._DISCONNECT_TIMEOUT", 0.01):
        await async_probe(hass, ADDRESS, "Bed", None)
