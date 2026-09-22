"""The under-bed light, where the receiver has one."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import LightEntity, LightEntityDescription
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OctoBedConfigEntry
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity

# Switching goes through the coordinator, which serialises the connection.
PARALLEL_UPDATES = 0

LIGHT = LightEntityDescription(key="light", translation_key="light")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OctoBedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the light if the receiver reported one."""
    coordinator = entry.runtime_data
    if coordinator.features.has_light:
        async_add_entities([OctoBedLight(coordinator, LIGHT)])


class OctoBedLight(OctoBedEntity, LightEntity):
    """On and off; the receiver does not say which it is."""

    _attr_assumed_state = True
    _attr_color_mode = ColorMode.ONOFF

    def __init__(
        self, coordinator: OctoBedCoordinator, description: LightEntityDescription
    ) -> None:
        """Bind the light to the bed."""
        super().__init__(coordinator, description)
        self._attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool:
        """Return what was last switched."""
        return self.coordinator.light_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the light on."""
        await self.coordinator.async_set_light(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the light off."""
        await self.coordinator.async_set_light(False)
