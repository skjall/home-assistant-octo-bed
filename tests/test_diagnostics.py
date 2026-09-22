"""Diagnostics leave the PIN and the address behind."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octo_bed.diagnostics import async_get_config_entry_diagnostics

from .conftest import FakeBed
from .test_init import _setup

DIAG = "custom_components.octo_bed.diagnostics"


async def test_diagnostics(
    hass: HomeAssistant,
    bluetooth_ready: None,
    mock_config_entry: MockConfigEntry,
    bed: FakeBed,
    service_info,
) -> None:
    await _setup(hass, mock_config_entry)
    empty = MagicMock()
    empty.scanner.name = "local"
    empty.scanner.get_allocations.return_value = None
    empty.advertisement.rssi = -90
    with (
        patch(f"{DIAG}.async_last_service_info", return_value=service_info),
        patch(
            f"{DIAG}.async_scanner_devices_by_address",
            return_value=[bed.path, empty],  # type: ignore[attr-defined]
        ),
    ):
        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result["entry"]["data"]["pin"] == "**REDACTED**"
    assert result["entry"]["data"]["address"] == "**REDACTED**"
    assert result["connection_paths"][0] == {
        "scanner": "proxy",
        "rssi": -70,
        "slots": 3,
        "free": 2,
    }
    assert result["connection_paths"][1]["slots"] is None
    assert result["advertisement"]["name"] == "RC2"
    assert result["coordinator"]["connected"] is False


async def test_diagnostics_without_an_advertisement(
    hass: HomeAssistant,
    bluetooth_ready: None,
    mock_config_entry: MockConfigEntry,
    bed: FakeBed,
) -> None:
    await _setup(hass, mock_config_entry)
    await mock_config_entry.runtime_data.async_move(2, True)
    with patch(f"{DIAG}.async_last_service_info", return_value=None):
        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result["advertisement"] is None
    assert result["coordinator"]["motion"]["up"] is True
    await mock_config_entry.runtime_data.async_shutdown()
