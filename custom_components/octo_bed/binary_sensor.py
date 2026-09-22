"""Whether a connection to the bed is open.

Mostly there to show that none stays open: the proxy's slots are shared.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OctoBedConfigEntry
from .entity import OctoBedEntity

# Reads coordinator state only; nothing to limit.
PARALLEL_UPDATES = 0

CONNECTION = BinarySensorEntityDescription(
    key="connection",
    translation_key="connection",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
    # It flips with every command; worth enabling when chasing slot trouble.
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OctoBedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the connection sensor."""
    async_add_entities([OctoBedConnection(entry.runtime_data, CONNECTION)])


class OctoBedConnection(OctoBedEntity, BinarySensorEntity):
    """On while Home Assistant holds a connection to the bed."""

    @property
    def is_on(self) -> bool:
        """Return whether a connection is open."""
        return self.coordinator.connected
