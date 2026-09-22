"""The flow, which the quality scale wants covered completely."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import octo_bed_protocol as protocol
import pytest
from homeassistant.config_entries import (
    SOURCE_BLUETOOTH,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octo_bed.config_flow import is_octo, suggested_title
from custom_components.octo_bed.const import (
    CONF_FEATURES,
    CONF_LISTING,
    CONF_PIN,
    DOMAIN,
    SERVICE_UUID,
)
from custom_components.octo_bed.coordinator import PinRejectedError, Probe

from .conftest import ADDRESS, PIN, make_service_info

PROBE = "custom_components.octo_bed.config_flow.async_probe"
DISCOVERED = "custom_components.octo_bed.config_flow.async_discovered_service_info"


def features(pin_set: bool = False, motors: int = 2, light: bool = True) -> Probe:
    return Probe(
        features=protocol.Features(
            motor_count=motors, has_light=light, pin_set=pin_set, complete=True
        ),
        received=[bytes.fromhex("40 21 71")],
    )


async def _discover(hass: HomeAssistant, info=None):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=info or make_service_info(),
    )


async def test_discovery_without_a_pin(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """A bed without a PIN is created right after the confirmation."""
    result = await _discover(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    with patch(PROBE, return_value=features()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "RC2 EEFF"
    assert result["data"][CONF_ADDRESS] == ADDRESS
    assert CONF_PIN not in result["data"]
    assert result["data"][CONF_FEATURES]["motor_count"] == 2
    # The raw listing travels with the entry, for the diagnostics.
    assert result["data"][CONF_LISTING] == ["40 21 71"]


async def test_discovery_with_a_pin(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """A PIN is asked for, checked for its form, then tried on the bed."""
    result = await _discover(hass)
    with patch(PROBE, return_value=features(pin_set=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pin"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "12"}
    )
    assert result["errors"] == {"base": "invalid_pin_format"}

    with patch(PROBE, side_effect=PinRejectedError):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: "9999"}
        )
    assert result["errors"] == {"base": "invalid_pin"}

    with patch(PROBE, return_value=features(pin_set=True)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: PIN}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PIN] == PIN


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (
            HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_free_slot"
            ),
            "no_free_slot",
        ),
        (HomeAssistantError("plain"), "cannot_connect"),
        (TimeoutError, "no_features"),
        (RuntimeError, "cannot_connect"),
    ],
)
async def test_discovery_errors(
    hass: HomeAssistant, side_effect: BaseException, error: str
) -> None:
    """Every failure lands in the form, not in the log."""
    result = await _discover(hass)
    with patch(PROBE, side_effect=side_effect):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": error}


async def test_a_bed_that_reports_nothing(hass: HomeAssistant) -> None:
    """No motors and no light is nothing to set up."""
    result = await _discover(hass)
    with patch(PROBE, return_value=features(motors=0, light=False)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "no_features"}


async def test_discovery_of_something_else(hass: HomeAssistant) -> None:
    """FFE0 alone, under a foreign name, is another bed family."""
    result = await _discover(
        hass, make_service_info(name="Solace", uuids=[SERVICE_UUID])
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_discovery_of_a_configured_bed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A bed that is set up is not offered again."""
    mock_config_entry.add_to_hass(hass)
    result = await _discover(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_the_user_picks_a_bed(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Beds in range are listed; foreign devices are not."""
    other = make_service_info(address="11:22:33:44:55:66", name="Kettle", uuids=[])
    with patch(DISCOVERED, return_value=[make_service_info(), other]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert list(result["data_schema"].schema[CONF_ADDRESS].container) == [ADDRESS]

        with patch(PROBE, return_value=features()):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_ADDRESS: ADDRESS}
            )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_user_finds_nothing(hass: HomeAssistant) -> None:
    """No bed in range ends the flow with a reason."""
    with patch(DISCOVERED, return_value=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_reauth(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """A new PIN replaces the old one and the entry reloads."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "abcd"}
    )
    assert result["errors"] == {"base": "invalid_pin_format"}

    with (
        patch(PROBE, return_value=features(pin_set=True)),
        patch("custom_components.octo_bed.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: "4321"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PIN] == "4321"


async def test_reconfigure_reads_the_bed_again(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """New features replace the old ones; a PIN is demanded where one is set."""
    mock_config_entry.add_to_hass(hass)
    loaded = AsyncMock()
    mock_config_entry.runtime_data = loaded
    mock_config_entry.mock_state(hass, ConfigEntryState.LOADED)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    with patch(PROBE, return_value=features(pin_set=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "pin_required"}
    # The running entry let go of the bed before the flow connected.
    loaded.async_disconnect.assert_awaited()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "1"}
    )
    assert result["errors"] == {"base": "invalid_pin_format"}

    with (
        patch(PROBE, return_value=features(pin_set=True, motors=3)),
        patch("custom_components.octo_bed.async_setup_entry", return_value=True),
        patch("custom_components.octo_bed.async_unload_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: PIN}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_FEATURES]["motor_count"] == 3


async def test_reconfigure_a_bed_without_a_pin(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A bed whose PIN was removed loses it from the entry too."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    with (
        patch(PROBE, return_value=features()),
        patch("custom_components.octo_bed.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reconfigure_successful"
    assert CONF_PIN not in mock_config_entry.data


def test_titles_and_recognition() -> None:
    """Two receivers of one bed get titles that tell them apart."""
    assert suggested_title(make_service_info(name="RC2")) == "RC2 EEFF"
    # The name one of the real receivers advertised.
    garbled = make_service_info(name="\x06C\x03�\x10")
    assert suggested_title(garbled) == "Octo EEFF"
    assert is_octo(garbled)
    assert is_octo(make_service_info(name="MC2 left", uuids=[SERVICE_UUID]))
    assert not is_octo(make_service_info(name="", uuids=[SERVICE_UUID]))
