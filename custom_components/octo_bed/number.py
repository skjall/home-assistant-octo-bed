"""Run times and connection timing, set per bed.

They take effect from the next movement on, without reloading anything.
"""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OctoBedConfigEntry
from .const import (
    CONF_DOWN_TIME,
    CONF_IDLE_TIMEOUT,
    CONF_POSITION_TIME,
    CONF_STEP_INTERVAL,
    CONF_UP_TIME,
    DEFAULTS,
)
from .entity import OctoBedEntity

# Setting a value writes the entry options; nothing goes to the bed.
PARALLEL_UPDATES = 0


NUMBERS: tuple[NumberEntityDescription, ...] = (
    NumberEntityDescription(
        key=CONF_UP_TIME,
        translation_key="up_time",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=1,
        native_max_value=120,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key=CONF_DOWN_TIME,
        translation_key="down_time",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=1,
        native_max_value=120,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key=CONF_POSITION_TIME,
        translation_key="position_time",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=1,
        native_max_value=180,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key=CONF_STEP_INTERVAL,
        translation_key="step_interval",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        native_min_value=100,
        native_max_value=1000,
        native_step=10,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key=CONF_IDLE_TIMEOUT,
        translation_key="idle_timeout",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=1,
        native_max_value=300,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OctoBedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the timing fields."""
    async_add_entities(
        OctoBedNumber(entry.runtime_data, description) for description in NUMBERS
    )


class OctoBedNumber(OctoBedEntity, NumberEntity):
    """One timing, stored with the entry."""

    @property
    def available(self) -> bool:
        """A setting can be changed whether or not the bed is in range."""
        return True

    @property
    def native_value(self) -> float:
        """Return the value in force."""
        key = self.entity_description.key
        return float(self.coordinator.entry.options.get(key, DEFAULTS[key]))

    async def async_set_native_value(self, value: float) -> None:
        """Store the new value; the next movement uses it."""
        self.coordinator.async_set_timing(self.entity_description.key, value)
