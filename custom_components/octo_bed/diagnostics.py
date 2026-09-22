"""Diagnostics for a configured bed."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.bluetooth import (
    async_last_service_info,
    async_scanner_devices_by_address,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import OctoBedConfigEntry
from .const import CONF_PIN

TO_REDACT = {CONF_PIN, CONF_ADDRESS}


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    return {k: ("**REDACTED**" if k in TO_REDACT else v) for k, v in data.items()}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OctoBedConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    service_info = async_last_service_info(hass, coordinator.address, connectable=True)

    paths = []
    for path in async_scanner_devices_by_address(
        hass, coordinator.address, connectable=True
    ):
        allocations = path.scanner.get_allocations()
        paths.append(
            {
                "scanner": path.scanner.name,
                "rssi": path.advertisement.rssi,
                # Counts only: the allocated addresses are other people's devices.
                "slots": allocations.slots if allocations else None,
                "free": allocations.free if allocations else None,
            }
        )

    return {
        "entry": {
            "data": _redact(dict(entry.data)),
            "options": dict(entry.options),
        },
        "coordinator": {
            "available": coordinator.available,
            "connected": coordinator.connected,
            "motion": asdict(coordinator.motion) if coordinator.motion else None,
            "light_on": coordinator.light_on,
            "timings": asdict(coordinator.timings),
        },
        "connection_paths": paths,
        "advertisement": {
            "name": service_info.name,
            "rssi": service_info.rssi,
            "source": service_info.source,
            "service_uuids": service_info.service_uuids,
        }
        if service_info
        else None,
    }
