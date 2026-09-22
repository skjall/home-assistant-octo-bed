"""Setting up, unloading, and what makes setup wait."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octo_bed.const import CONF_FEATURES, CONF_MOVE_STEPS

from .conftest import make_service_info

INIT = "custom_components.octo_bed.bluetooth"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    with (
        patch(f"{INIT}.async_scanner_count", return_value=1),
        patch(f"{INIT}.async_address_present", return_value=True),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
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
        "feet",
        "flat",
        "head",
        "light",
        "memory_1",
        "memory_2",
        "stop",
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


async def test_new_options_reload(
    hass: HomeAssistant, bluetooth_ready: None, mock_config_entry: MockConfigEntry
) -> None:
    """Changed timings take effect without a restart."""
    await _setup(hass, mock_config_entry)
    with (
        patch(f"{INIT}.async_scanner_count", return_value=1),
        patch(f"{INIT}.async_address_present", return_value=True),
    ):
        hass.config_entries.async_update_entry(
            mock_config_entry, options={CONF_MOVE_STEPS: 7}
        )
        await hass.async_block_till_done()
    assert mock_config_entry.runtime_data.timings.move_steps == 7


async def test_shutdown_hangs_up(
    hass: HomeAssistant, bluetooth_ready: None, mock_config_entry: MockConfigEntry
) -> None:
    """Stopping Home Assistant closes an open connection."""
    await _setup(hass, mock_config_entry)
    with patch.object(mock_config_entry.runtime_data, "async_shutdown") as shutdown:
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()
    shutdown.assert_awaited()
