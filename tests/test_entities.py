"""The entities: what they call, and what they show."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import octo_bed_protocol as protocol
import pytest
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octo_bed.const import DOMAIN, MOTOR_FEET, MOTOR_HEAD

from .conftest import ADDRESS, FakeBed
from .test_init import _setup

BOTH = MOTOR_HEAD | MOTOR_FEET


@pytest.fixture
async def loaded(
    hass: HomeAssistant,
    bluetooth_ready: None,
    mock_config_entry: MockConfigEntry,
    bed: FakeBed,
) -> AsyncGenerator[MockConfigEntry]:
    await _setup(hass, mock_config_entry)
    yield mock_config_entry
    await mock_config_entry.runtime_data.async_shutdown()


async def _call(hass: HomeAssistant, domain: str, service: str, entity: str) -> None:
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity}, blocking=True
    )


async def test_covers_drive_their_motors(
    hass: HomeAssistant, loaded: MockConfigEntry, bed: FakeBed
) -> None:
    """Open raises, close lowers, stop stops - and the state says which."""
    await _call(hass, "cover", "open_cover", "cover.bed_head")
    assert hass.states.get("cover.bed_head").state == "opening"
    assert bed.frames(protocol.move(MOTOR_HEAD, True)) >= 1

    await _call(hass, "cover", "close_cover", "cover.bed_all_motors")
    assert hass.states.get("cover.bed_all_motors").state == "closing"
    assert hass.states.get("cover.bed_head").state == "unknown"

    await _call(hass, "cover", "stop_cover", "cover.bed_feet")
    assert bed.written[-1] == protocol.stop()
    assert hass.states.get("cover.bed_all_motors").state == "unknown"


async def test_the_light(
    hass: HomeAssistant, loaded: MockConfigEntry, bed: FakeBed
) -> None:
    """On and off, as last switched."""
    assert hass.states.get("light.bed_light").state == STATE_OFF
    await _call(hass, "light", "turn_on", "light.bed_light")
    assert hass.states.get("light.bed_light").state == STATE_ON
    await _call(hass, "light", "turn_off", "light.bed_light")
    assert hass.states.get("light.bed_light").state == STATE_OFF
    assert bed.written[-1] == protocol.set_light(False)


async def test_the_buttons(
    hass: HomeAssistant, loaded: MockConfigEntry, bed: FakeBed
) -> None:
    """Flat, a stored position, and stop."""
    await _call(hass, "button", "press", "button.bed_flat")
    assert bed.frames(protocol.move(BOTH, False)) >= 1
    await _call(hass, "button", "press", "button.bed_memory_position_2")
    assert bed.frames(protocol.recall_memory(1)) >= 1
    await _call(hass, "button", "press", "button.bed_stop")
    assert bed.written[-1] == protocol.stop()


async def test_the_connection_sensor_starts_disabled(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    """It flips with every command, so it is opt-in."""
    entry = er.async_get(hass).async_get("binary_sensor.bed_connection")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_the_connection_sensor_follows_the_connection(
    hass: HomeAssistant,
    bluetooth_ready: None,
    mock_config_entry: MockConfigEntry,
    bed: FakeBed,
) -> None:
    """Off at rest, on while a command holds the connection."""
    mock_config_entry.add_to_hass(hass)
    # Enabled by the user before setup, as it would be after the first one.
    er.async_get(hass).async_get_or_create(
        "binary_sensor",
        DOMAIN,
        f"{ADDRESS}_connection",
        config_entry=mock_config_entry,
        suggested_object_id="bed_connection",
    )
    await _setup(hass, mock_config_entry)
    entity_id = "binary_sensor.bed_connection"
    assert hass.states.get(entity_id).state == STATE_OFF
    await _call(hass, "light", "turn_on", "light.bed_light")
    assert hass.states.get(entity_id).state == STATE_ON
    await mock_config_entry.runtime_data.async_shutdown()
    assert hass.states.get(entity_id).state == STATE_OFF


async def test_unavailable_when_gone(
    hass: HomeAssistant, loaded: MockConfigEntry, bed: FakeBed
) -> None:
    """Out of range and not connected means unavailable."""
    coordinator = loaded.runtime_data
    coordinator._available = False
    coordinator.async_update_listeners()
    await asyncio.sleep(0)
    assert hass.states.get("cover.bed_head").state == STATE_UNAVAILABLE
