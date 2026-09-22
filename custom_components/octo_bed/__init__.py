"""Octo adjustable beds over Bluetooth."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_FEATURES, CONF_PIN, DOMAIN
from .coordinator import OctoBedCoordinator, Timings, features_from_data

type OctoBedConfigEntry = ConfigEntry[OctoBedCoordinator]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.LIGHT,
]


async def async_setup_entry(hass: HomeAssistant, entry: OctoBedConfigEntry) -> bool:
    """Set up one bed from a config entry.

    No connection is opened here. The bed is only checked for being in range;
    the first command connects.
    """
    address = entry.data[CONF_ADDRESS]

    if not bluetooth.async_scanner_count(hass, connectable=True):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="no_scanner"
        )
    if not bluetooth.async_address_present(hass, address, connectable=True):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="not_in_range",
            translation_placeholders={"address": address},
        )

    coordinator = OctoBedCoordinator(
        hass,
        entry,
        address,
        entry.data.get(CONF_PIN),
        features_from_data(entry.data[CONF_FEATURES]),
        Timings.from_options(entry.options),
    )
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Only start once every platform has had its chance to subscribe.
    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(coordinator.async_shutdown)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def _async_stop(_: Event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: OctoBedConfigEntry
) -> None:
    """Reload so the new timings take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: OctoBedConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
