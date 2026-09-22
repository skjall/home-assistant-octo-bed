"""Setting up, unloading, and what makes setup wait."""

from __future__ import annotations

from unittest.mock import patch

import octo_bed_protocol as protocol
from bleak.exc import BleakError
from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octo_bed.const import (
    CONF_FEATURES,
    CONF_LISTING,
)

from .conftest import PIN, PIN_WRONG, FakeBed, make_service_info

INIT = "custom_components.octo_bed.bluetooth"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    with (
        patch(f"{INIT}.async_scanner_count", return_value=1),
        patch(f"{INIT}.async_address_present", return_value=True),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    if entry.state is not ConfigEntryState.LOADED:
        return
    # One advertisement, as the bed sends them all the time.
    entry.runtime_data._async_handle_bluetooth_event(
        make_service_info(), BluetoothChange.ADVERTISEMENT
    )


async def test_setup_creates_what_the_bed_has(
    hass: HomeAssistant, bluetooth_ready: None, mock_config_entry: MockConfigEntry
) -> None:
    """Two motors, two memories and a light make exactly these entities."""
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    keys = sorted(
        e.unique_id.split("_", 1)[1]
        for e in er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
    )
    assert keys == [
        "all_motors",
        "connection",
        "down_time",
        "feet",
        "flat",
        "head",
        "idle_timeout",
        "light",
        "memory_1",
        "memory_2",
        "position_time",
        "step_interval",
        "stop",
        "up_time",
    ]

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_a_bed_with_one_motor_and_no_light(
    hass: HomeAssistant, bluetooth_ready: None, mock_config_entry: MockConfigEntry
) -> None:
    """One motor has no 'all motors', and no light means no light entity."""
    features = {
        **mock_config_entry.data[CONF_FEATURES],
        "motor_count": 1,
        "memory_count": 0,
        "has_light": False,
    }
    entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        title="Bed",
        unique_id=mock_config_entry.unique_id,
        data={**mock_config_entry.data, CONF_FEATURES: features},
    )
    await _setup(hass, entry)
    assert hass.states.get("cover.bed_head") is not None
    assert hass.states.get("cover.bed_all_motors") is None
    assert hass.states.get("light.bed_light") is None
    assert hass.states.get("button.bed_flat") is not None


async def test_setup_waits_for_an_adapter(
    hass: HomeAssistant, bluetooth_ready: None, mock_config_entry: MockConfigEntry
) -> None:
    """No connectable adapter is a reason to retry, not an error."""
    mock_config_entry.add_to_hass(hass)
    with patch(f"{INIT}.async_scanner_count", return_value=0):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_waits_for_the_bed(
    hass: HomeAssistant, bluetooth_ready: None, mock_config_entry: MockConfigEntry
) -> None:
    """A bed out of range is retried as well."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch(f"{INIT}.async_scanner_count", return_value=1),
        patch(f"{INIT}.async_address_present", return_value=False),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_shutdown_hangs_up(
    hass: HomeAssistant, bluetooth_ready: None, mock_config_entry: MockConfigEntry
) -> None:
    """Stopping Home Assistant closes an open connection."""
    await _setup(hass, mock_config_entry)
    with patch.object(mock_config_entry.runtime_data, "async_shutdown") as shutdown:
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()
    shutdown.assert_awaited()


def _old_entry(entry: MockConfigEntry) -> MockConfigEntry:
    """An entry from before the listing was stored: motors lost."""
    data = {k: v for k, v in entry.data.items() if k != CONF_LISTING}
    data[CONF_FEATURES] = {**data[CONF_FEATURES], "motor_count": None}
    return MockConfigEntry(
        domain=entry.domain, title="Bed", unique_id=entry.unique_id, data=data
    )


async def test_an_old_entry_reads_its_features_again(
    hass: HomeAssistant,
    bluetooth_ready: None,
    mock_config_entry: MockConfigEntry,
    bed: FakeBed,
) -> None:
    """Once, at setup, and the motors appear."""
    entry = _old_entry(mock_config_entry)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_FEATURES]["motor_count"] == 2
    assert entry.data[CONF_LISTING]
    assert hass.states.get("cover.bed_head") is not None
    assert bed.written == [protocol.request_features(), protocol.pin(PIN)]
    bed.client.disconnect.assert_awaited()
    await entry.runtime_data.async_shutdown()


async def test_an_old_entry_waits_when_the_bed_is_unreachable(
    hass: HomeAssistant,
    bluetooth_ready: None,
    mock_config_entry: MockConfigEntry,
    bed: FakeBed,
) -> None:
    """No answer means retry later, not an entry without motors."""
    entry = _old_entry(mock_config_entry)
    with patch(
        "custom_components.octo_bed.coordinator.establish_connection",
        side_effect=BleakError("busy"),
    ):
        await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert CONF_LISTING not in entry.data


async def test_an_old_entry_with_a_wrong_pin(
    hass: HomeAssistant,
    bluetooth_ready: None,
    mock_config_entry: MockConfigEntry,
    bed: FakeBed,
) -> None:
    """A PIN the bed refuses asks for a new one."""
    bed.replies[protocol.pin(PIN)] = PIN_WRONG
    entry = _old_entry(mock_config_entry)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == SOURCE_REAUTH
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_features_come_from_the_stored_listing(
    hass: HomeAssistant,
    bluetooth_ready: None,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A parser that learned better fixes an entry without a new connection."""
    rc2 = [
        "40 21 71 00 07 e2 00 00 01 01 01 02 00 40",
        "40 21 71 00 08 df 00 01 02 01 01 01 01 00 40",
        "40 21 71 00 06 ea ff ff ff 01 00 00 40",
    ]
    stale = {**mock_config_entry.data[CONF_FEATURES], "motor_count": None}
    entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        title="Bed",
        unique_id=mock_config_entry.unique_id,
        data={**mock_config_entry.data, CONF_FEATURES: stale, CONF_LISTING: rc2},
    )
    await _setup(hass, entry)
    assert entry.data[CONF_FEATURES]["motor_count"] == 2
    assert hass.states.get("cover.bed_head") is not None
    assert hass.states.get("cover.bed_feet") is not None
    assert hass.states.get("cover.bed_all_motors") is not None
    await entry.runtime_data.async_shutdown()
