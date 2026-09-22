"""The motors, one cover each, plus one that drives them all together.

The receiver reports no positions, so every cover is in an assumed state: open
and close stay available whatever happened last, and the state shows only
whether a movement is running.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityDescription,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OctoBedConfigEntry
from .const import MOTOR_3, MOTOR_4, MOTOR_FEET, MOTOR_HEAD
from .coordinator import OctoBedCoordinator
from .entity import OctoBedEntity

# Every action goes through the coordinator, which serialises the connection.
# A stop must never wait behind a movement that is still connecting.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class OctoBedCoverDescription(CoverEntityDescription):
    """A cover and the motor bits behind it; zero means every motor."""

    motors: int


MOTORS: tuple[OctoBedCoverDescription, ...] = (
    OctoBedCoverDescription(key="head", translation_key="head", motors=MOTOR_HEAD),
    OctoBedCoverDescription(key="feet", translation_key="feet", motors=MOTOR_FEET),
    OctoBedCoverDescription(key="motor_3", translation_key="motor_3", motors=MOTOR_3),
    OctoBedCoverDescription(key="motor_4", translation_key="motor_4", motors=MOTOR_4),
)
ALL_MOTORS = OctoBedCoverDescription(
    key="all_motors", translation_key="all_motors", motors=0
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OctoBedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one cover per motor the receiver reported."""
    coordinator = entry.runtime_data
    mask = coordinator.features.motor_mask()
    covers = [
        OctoBedCover(coordinator, description)
        for description in MOTORS
        if mask & description.motors
    ]
    if len(covers) > 1:
        covers.append(OctoBedCover(coordinator, ALL_MOTORS))
    async_add_entities(covers)


class OctoBedCover(OctoBedEntity, CoverEntity):
    """One motor, or several driven together."""

    entity_description: OctoBedCoverDescription

    _attr_assumed_state = True
    _attr_is_closed = None
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(
        self, coordinator: OctoBedCoordinator, description: OctoBedCoverDescription
    ) -> None:
        """Bind the cover to its motor bits."""
        super().__init__(coordinator, description)
        self._motors = description.motors or coordinator.features.motor_mask()

    def _moving(self, up: bool) -> bool:
        motion = self.coordinator.motion
        return motion is not None and motion.motors == self._motors and motion.up is up

    @property
    def is_opening(self) -> bool:
        """Return whether this motor is being raised."""
        return self._moving(True)

    @property
    def is_closing(self) -> bool:
        """Return whether this motor is being lowered."""
        return self._moving(False)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Raise."""
        await self.coordinator.async_move(self._motors, True)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Lower."""
        await self.coordinator.async_move(self._motors, False)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop - every motor, since the receiver knows no other stop."""
        await self.coordinator.async_stop()
