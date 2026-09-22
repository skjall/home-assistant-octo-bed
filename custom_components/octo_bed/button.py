"""Stop, flat, and the stored positions the receiver reported."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OctoBedConfigEntry
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity

# Every press goes through the coordinator, which serialises the connection.
# Stop in particular must not queue behind anything.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class OctoBedButtonDescription(ButtonEntityDescription):
    """A button and what pressing it asks of the coordinator."""

    press: Callable[[OctoBedCoordinator], Awaitable[None]]


STOP = OctoBedButtonDescription(
    key="stop", translation_key="stop", press=lambda c: c.async_stop()
)
FLAT = OctoBedButtonDescription(
    key="flat", translation_key="flat", press=lambda c: c.async_flat()
)


def memory(slot: int) -> OctoBedButtonDescription:
    """Describe the button for one memory slot, counted from zero."""
    return OctoBedButtonDescription(
        key=f"memory_{slot + 1}",
        translation_key="memory",
        translation_placeholders={"slot": str(slot + 1)},
        press=lambda c: c.async_recall_memory(slot),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OctoBedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the buttons that fit what the receiver has."""
    coordinator = entry.runtime_data
    descriptions = [STOP]
    if coordinator.features.motor_mask():
        descriptions.append(FLAT)
    descriptions.extend(
        memory(slot) for slot in range(coordinator.features.memory_count)
    )
    async_add_entities(
        OctoBedButton(coordinator, description) for description in descriptions
    )


class OctoBedButton(OctoBedEntity, ButtonEntity):
    """One press, one coordinator call."""

    entity_description: OctoBedButtonDescription

    async def async_press(self) -> None:
        """Do what the button says."""
        await self.entity_description.press(self.coordinator)
