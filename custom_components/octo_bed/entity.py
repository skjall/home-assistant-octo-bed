"""Shared base: every entity hangs off the same bed."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityDescription

from .const import DOMAIN, MANUFACTURER
from .coordinator import OctoBedCoordinator


class OctoBedEntity(PassiveBluetoothCoordinatorEntity[OctoBedCoordinator]):
    """Base entity for one bed."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: OctoBedCoordinator, description: EntityDescription
    ) -> None:
        """Tie this entity to one bed; name and icon come from the description."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer=MANUFACTURER,
            name=coordinator.device_name,
        )

    @property
    def available(self) -> bool:
        """In range, or connected right now.

        A bed stops advertising while it is connected, so advertisements alone
        would call it gone at the very moment it is in use.
        """
        return self.coordinator.available
