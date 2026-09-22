"""Octo adjustable beds over Bluetooth."""

from __future__ import annotations

import octo_bed_protocol as protocol
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)

from .const import CONF_FEATURES, CONF_LISTING, CONF_PIN, DOMAIN
from .coordinator import (
    OctoBedCoordinator,
    PinRejectedError,
    Timings,
    async_probe,
    features_from_data,
    features_to_data,
)

type OctoBedConfigEntry = ConfigEntry[OctoBedCoordinator]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.LIGHT,
    Platform.NUMBER,
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

    if CONF_LISTING not in entry.data:
        await _async_read_features_again(hass, entry)

    coordinator = OctoBedCoordinator(
        hass,
        entry,
        address,
        entry.data.get(CONF_PIN),
        _features(hass, entry),
        Timings.from_options(entry.options),
    )
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Only start once every platform has had its chance to subscribe.
    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(coordinator.async_shutdown)

    async def _async_stop(_: Event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    return True


def _features(hass: HomeAssistant, entry: OctoBedConfigEntry) -> protocol.Features:
    """Read the features from the listing the bed sent, every time.

    The listing is what the bed said; the features are only one reading of
    it. Reading it again at each start means a corrected parser reaches every
    existing entry without connecting to the bed or setting it up again.
    """
    listing = [bytes.fromhex(chunk) for chunk in entry.data[CONF_LISTING]]
    if not listing:
        return features_from_data(entry.data[CONF_FEATURES])
    features = protocol.read_listing(listing)
    if (data := features_to_data(features)) != entry.data[CONF_FEATURES]:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_FEATURES: data}
        )
    return features


async def _async_read_features_again(
    hass: HomeAssistant, entry: OctoBedConfigEntry
) -> None:
    """Read the features of an entry that was set up by an older reader.

    Before the raw listing was stored with the entry, the reader cut frames
    at every 0x40 and lost each record that contained one - on an RC2 the
    motor count. Such an entry has no listing, and its features are read once
    more: one short connection, closed again straight away.
    """
    try:
        probe = await async_probe(
            hass, entry.data[CONF_ADDRESS], entry.title, entry.data.get(CONF_PIN)
        )
    except PinRejectedError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_pin"
        ) from err
    except (HomeAssistantError, TimeoutError, BleakError) as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="features_unread",
            translation_placeholders={"name": entry.title},
        ) from err
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_FEATURES: features_to_data(probe.features),
            CONF_LISTING: [chunk.hex(" ") for chunk in probe.received],
        },
    )


async def async_unload_entry(hass: HomeAssistant, entry: OctoBedConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
