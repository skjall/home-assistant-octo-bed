"""Talking to one bed.

There is nothing to poll: the receiver reports neither positions nor state.
So the coordinator only listens to advertisements, which is what tells Home
Assistant the bed is in range, and opens a connection when there is a command
to send.

That connection is closed again as soon as the bed has been left alone for a
few seconds. A Bluetooth proxy has only a handful of connection slots, and a
bed that holds one around the clock takes it from every other device the proxy
could serve.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

import octo_bed_protocol as protocol
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CHAR_UUID,
    CONF_DOWN_TIME,
    CONF_IDLE_TIMEOUT,
    CONF_POSITION_TIME,
    CONF_STEP_INTERVAL,
    CONF_UP_TIME,
    DEFAULTS,
    DOMAIN,
    KEEPALIVE_INTERVAL,
)

if TYPE_CHECKING:
    from bleak import BleakClient
    from bleak.backends.characteristic import BleakGATTCharacteristic

    from . import OctoBedConfigEntry

_LOGGER = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 20.0
# Connecting, subscribing and unlocking together. Three connection attempts fit;
# a GATT call that never returns does not, and must not hold the lock forever.
_SESSION_TIMEOUT = 75.0
_WRITE_TIMEOUT = 5.0
_DISCONNECT_TIMEOUT = 10.0
# Receivers with a PIN answer it at once; one without may not answer at all.
_PIN_REPLY_TIMEOUT = 3.0
# The feature listing is a dozen short notifications.
_FEATURE_TIMEOUT = 10.0


class PinRejectedError(Exception):
    """The receiver said no to the PIN."""


@dataclass
class Probe:
    """What one setup connection learned, and the bytes it learned it from."""

    features: protocol.Features
    # Every notification as received, so a listing that was misread can be
    # read again from the diagnostics instead of from a new capture.
    received: list[bytes]


@dataclass(frozen=True)
class Timings:
    """How movements are driven and how long a connection stays open."""

    step_interval: float
    up_time: float
    down_time: float
    position_time: float
    idle_timeout: float
    keepalive_interval: float = KEEPALIVE_INTERVAL

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Timings:
        """Read the timings from the entry options, defaults where absent."""

        def get(key: str) -> float:
            return float(options.get(key, DEFAULTS[key]))

        return cls(
            step_interval=get(CONF_STEP_INTERVAL) / 1000,
            up_time=get(CONF_UP_TIME),
            down_time=get(CONF_DOWN_TIME),
            position_time=get(CONF_POSITION_TIME),
            idle_timeout=get(CONF_IDLE_TIMEOUT),
        )

    def steps(self, seconds: float) -> int:
        """Return how many steps fill a run time; always at least one."""
        return max(1, round(seconds / self.step_interval))


@dataclass(frozen=True)
class Motion:
    """What the bed is doing right now, as far as we drive it."""

    motors: int
    up: bool | None = None
    memory: int | None = None


def features_to_data(features: protocol.Features) -> dict[str, Any]:
    """Keep what setup learned about the receiver, for the entry."""
    data = asdict(features)
    # Session state, not a property of the bed.
    for key in ("complete", "pin_unlocked"):
        data.pop(key)
    return data


def features_from_data(data: Mapping[str, Any]) -> protocol.Features:
    """Rebuild the features stored with the entry."""
    return protocol.Features(**data, complete=True)


def _ble_device(hass: HomeAssistant, address: str) -> Any:
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if device is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="not_in_range",
            translation_placeholders={"address": address},
        )
    return device


def check_free_slot(hass: HomeAssistant, address: str) -> None:
    """Fail fast when every adapter that hears the bed is out of slots.

    The connection path is chosen by Home Assistant, which already prefers an
    adapter with a free slot. This only turns the case where none has one into
    a message that says so, instead of a connection timeout.
    """
    paths = bluetooth.async_scanner_devices_by_address(hass, address, connectable=True)
    if not paths:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="not_in_range",
            translation_placeholders={"address": address},
        )
    reported = [
        allocations
        for path in paths
        if (allocations := path.scanner.get_allocations()) and allocations.slots > 0
    ]
    if len(reported) == len(paths) and all(a.free == 0 for a in reported):
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="no_free_slot",
            translation_placeholders={
                "adapters": ", ".join(sorted(path.scanner.name for path in paths))
            },
        )


async def _close(client: BleakClient) -> None:
    """Hang up, with a deadline: a disconnect that never returns holds a lock."""
    try:
        async with asyncio.timeout(_DISCONNECT_TIMEOUT):
            await client.disconnect()
    except (TimeoutError, BleakError) as err:
        _LOGGER.debug("Disconnecting failed: %s", err)


async def async_probe(
    hass: HomeAssistant, address: str, name: str, pin: str | None
) -> Probe:
    """Connect once, ask the receiver what it has, try the PIN, hang up.

    Used by the setup flow, before an entry exists. Raises PinRejectedError
    for a wrong PIN, HomeAssistantError when the bed cannot be reached, and
    TimeoutError when it never finishes listing its features.
    """
    check_free_slot(hass, address)
    device = _ble_device(hass, address)
    reader = protocol.FrameReader()
    features = protocol.Features()
    received: list[bytes] = []
    listed = asyncio.Event()
    pin_reply: asyncio.Future[bool] = hass.loop.create_future()

    def on_notify(_: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("%s: received %s", address, data.hex(" "))
        received.append(bytes(data))
        for packet in reader.feed(bytes(data)):
            features.add(packet)
            if features.complete:
                listed.set()
            accepted = protocol.pin_accepted(packet)
            if accepted is not None and not pin_reply.done():
                pin_reply.set_result(accepted)

    client = await establish_connection(
        BleakClientWithServiceCache,
        device,
        name,
        max_attempts=3,
        timeout=_CONNECT_TIMEOUT,
    )
    try:
        await client.start_notify(CHAR_UUID, on_notify)
        await client.write_gatt_char(CHAR_UUID, protocol.request_features())
        async with asyncio.timeout(_FEATURE_TIMEOUT):
            await listed.wait()
        if pin and features.pin_set:
            await client.write_gatt_char(CHAR_UUID, protocol.pin(pin))
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(_PIN_REPLY_TIMEOUT):
                    if not await pin_reply:
                        raise PinRejectedError
    finally:
        await _close(client)
    return Probe(features=features, received=received)


class OctoBedCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """One bed: in range or not, and a connection only while it is used."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: OctoBedConfigEntry,
        address: str,
        pin: str | None,
        features: protocol.Features,
        timings: Timings,
    ) -> None:
        """Set up the coordinator for one bed."""
        super().__init__(
            hass,
            _LOGGER,
            address,
            bluetooth.BluetoothScanningMode.PASSIVE,
            connectable=True,
        )
        self.entry = entry
        self.device_name = entry.title
        self.features = features
        self.timings = timings
        # Only sent to a receiver that said it has a PIN set.
        self._pin = pin if pin and features.pin_set else None

        self.motion: Motion | None = None
        # The receiver does not report the light; this is what we last set.
        self.light_on = features.light_on

        self._client: BleakClient | None = None
        # Which connection a disconnect callback belongs to. A late callback
        # from a connection that is already closed must not end the next one.
        self._generation = 0
        self._session_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._reader = protocol.FrameReader()
        self._pin_reply: asyncio.Future[bool] | None = None
        self._motion_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._idle_handle: asyncio.TimerHandle | None = None
        # Counts every use of the connection. An idle timeout that fires while
        # a command is on its way must not hang up underneath it.
        self._activity = 0

    @property
    def connected(self) -> bool:
        """Whether a connection to the bed is open right now."""
        return self._client is not None

    @property
    def available(self) -> bool:
        """In range, or connected - a connected bed stops advertising."""
        return super().available or self.connected

    # --- the connection ---------------------------------------------------

    async def _async_session(self) -> BleakClient:
        """Return an open, unlocked connection, opening one if needed."""
        self._activity += 1
        self._cancel_idle()
        async with self._session_lock:
            if self._client is not None:
                return self._client
            check_free_slot(self.hass, self.address)
            device = _ble_device(self.hass, self.address)
            self._generation += 1
            client: BleakClient | None = None
            try:
                async with asyncio.timeout(_SESSION_TIMEOUT):
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        device,
                        self.device_name,
                        disconnected_callback=partial(
                            self._on_disconnect, self._generation
                        ),
                        max_attempts=3,
                        timeout=_CONNECT_TIMEOUT,
                    )
                    self._reader = protocol.FrameReader()
                    await client.start_notify(CHAR_UUID, self._on_notify)
                    await self._async_unlock(client)
            except BaseException:
                if client is not None:
                    await _close(client)
                raise
            _LOGGER.debug("%s: connected", self.address)
            self._client = client
            if self._pin:
                self._keepalive_task = self.hass.async_create_background_task(
                    self._async_keepalive(), f"{DOMAIN} {self.address} keepalive"
                )
            self.async_update_listeners()
            return client

    async def _async_unlock(self, client: BleakClient) -> None:
        """Send the PIN and wait briefly for the verdict."""
        if not self._pin:
            return
        self._pin_reply = self.hass.loop.create_future()
        try:
            await self._async_write(protocol.pin(self._pin), client)
            async with asyncio.timeout(_PIN_REPLY_TIMEOUT):
                accepted = await self._pin_reply
        except TimeoutError:
            # Not every receiver answers. A wrong PIN still shows, as commands
            # the bed ignores and a reply the next time it does answer.
            return
        finally:
            self._pin_reply = None
        if not accepted:
            raise PinRejectedError

    async def _async_keepalive(self) -> None:
        """Repeat the PIN while the connection is open."""
        assert self._pin is not None
        frame = protocol.pin(self._pin)
        while True:
            await asyncio.sleep(self.timings.keepalive_interval)
            try:
                await self._async_write(frame)
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("%s: keepalive failed: %s", self.address, err)
                return

    @callback
    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("%s: received %s", self.address, data.hex(" "))
        for packet in self._reader.feed(bytes(data)):
            accepted = protocol.pin_accepted(packet)
            if accepted is not None:
                if self._pin_reply is not None and not self._pin_reply.done():
                    self._pin_reply.set_result(accepted)
                elif not accepted:
                    _LOGGER.warning("%s: the bed rejected the PIN", self.address)
            elif packet.command == protocol.REPLY_PIN_LOCK and self._pin:
                # The receiver locked itself again and asks for the PIN.
                self.hass.async_create_background_task(
                    self._async_resend_pin(), f"{DOMAIN} {self.address} pin"
                )

    async def _async_resend_pin(self) -> None:
        assert self._pin is not None
        with contextlib.suppress(BleakError, TimeoutError):
            await self._async_write(protocol.pin(self._pin))

    @callback
    def _on_disconnect(self, generation: int, _: BleakClient) -> None:
        """Clean up after the link went away underneath us."""
        if generation != self._generation or self._client is None:
            return
        _LOGGER.debug("%s: disconnected by the bed", self.address)
        self._client = None
        self._cancel_idle()
        self._cancel_keepalive()
        if self._motion_task is not None:
            self._motion_task.cancel()
        self.async_update_listeners()

    async def _async_write(
        self, frame: bytes, client: BleakClient | None = None
    ) -> None:
        client = client or self._client
        if client is None:
            raise BleakError("not connected")
        async with self._write_lock, asyncio.timeout(_WRITE_TIMEOUT):
            await client.write_gatt_char(CHAR_UUID, frame)

    def _cancel_keepalive(self) -> None:
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            self._keepalive_task = None

    def _cancel_idle(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    @callback
    def _schedule_idle(self) -> None:
        """Hang up once the bed has been left alone for a while."""
        self._cancel_idle()
        if self._client is None or self._motion_task is not None:
            return
        self._idle_handle = self.hass.loop.call_later(
            self.timings.idle_timeout, self._idle_expired
        )

    @callback
    def _idle_expired(self) -> None:
        self._idle_handle = None
        self.hass.async_create_background_task(
            self._async_idle_disconnect(self._activity),
            f"{DOMAIN} {self.address} disconnect",
        )

    async def _async_idle_disconnect(self, activity: int) -> None:
        async with self._session_lock:
            if activity != self._activity or self._motion_task is not None:
                return
            await self._async_close_session()
        self.async_update_listeners()

    async def async_disconnect(self) -> None:
        """Close the connection, if one is open."""
        async with self._session_lock:
            await self._async_close_session()
        self.async_update_listeners()

    async def _async_close_session(self) -> None:
        self._cancel_idle()
        self._cancel_keepalive()
        client, self._client = self._client, None
        if client is not None:
            _LOGGER.debug("%s: disconnecting", self.address)
            await _close(client)

    async def async_shutdown(self) -> None:
        """Stop whatever runs and hang up; for unload and shutdown."""
        moving = self._motion_task is not None
        await self._async_cancel_motion()
        if moving and self._client is not None:
            with contextlib.suppress(BleakError, TimeoutError):
                await self._async_write(protocol.stop())
        await self.async_disconnect()

    # --- commands ---------------------------------------------------------

    async def _async_command(self, frame: bytes) -> None:
        """Send one frame, connecting first if needed."""
        try:
            client = await self._async_session()
            await self._async_write(frame, client)
        except PinRejectedError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_pin"
            ) from err
        except (BleakError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"name": self.device_name},
            ) from err

    async def _async_cancel_motion(self) -> None:
        task, self._motion_task = self._motion_task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self.motion = None

    async def _async_drive(self, motion: Motion, frame: bytes, steps: int) -> None:
        """Send the first step now, the rest in the background, then stop.

        The first step is awaited so that a bed that cannot be reached fails
        the action the user took, rather than a task nobody watches.
        """
        await self._async_cancel_motion()
        await self._async_command(frame)
        self.motion = motion
        self._motion_task = self.hass.async_create_background_task(
            self._async_repeat(frame, steps), f"{DOMAIN} {self.address} motion"
        )
        self.async_update_listeners()

    async def _async_repeat(self, frame: bytes, steps: int) -> None:
        try:
            for _ in range(steps - 1):
                await asyncio.sleep(self.timings.step_interval)
                await self._async_write(frame)
            await asyncio.sleep(self.timings.step_interval)
            await self._async_write(protocol.stop())
        except (BleakError, TimeoutError) as err:
            _LOGGER.warning("%s: the movement broke off: %s", self.address, err)
        finally:
            if self._motion_task is asyncio.current_task():
                self._motion_task = None
                self.motion = None
                self._schedule_idle()
                self.async_update_listeners()

    async def async_move(self, motors: int, up: bool) -> None:
        """Run motors in one direction for that direction's run time."""
        seconds = self.timings.up_time if up else self.timings.down_time
        await self._async_drive(
            Motion(motors=motors, up=up),
            protocol.move(motors, up),
            self.timings.steps(seconds),
        )

    async def async_flat(self) -> None:
        """Lower every motor, for long enough to reach the bottom."""
        motors = self.features.motor_mask()
        await self._async_drive(
            Motion(motors=motors, up=False),
            protocol.move(motors, False),
            self.timings.steps(self.timings.position_time),
        )

    async def async_recall_memory(self, slot: int) -> None:
        """Drive towards a stored position; the bed stops when it gets there."""
        await self._async_drive(
            Motion(motors=0, memory=slot),
            protocol.recall_memory(slot),
            self.timings.steps(self.timings.position_time),
        )

    async def async_stop(self) -> None:
        """Stop every motor.

        Without an open connection nothing can be moving - the receiver stops
        on its own when the steps stop arriving - so there is nothing to send.
        """
        await self._async_cancel_motion()
        if self._client is None:
            self.async_update_listeners()
            return
        await self._async_command(protocol.stop())
        self._schedule_idle()
        self.async_update_listeners()

    @callback
    def async_set_timing(self, key: str, value: float) -> None:
        """Change one timing; it applies from the next movement on.

        Stored in the entry options, so it survives a restart, but without
        reloading the entry: that would drop a connection for nothing.
        """
        options = {**self.entry.options, key: value}
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self.timings = Timings.from_options(options)
        self.async_update_listeners()

    async def async_set_light(self, on: bool) -> None:
        """Switch the under-bed light."""
        await self._async_command(protocol.set_light(on))
        self.light_on = on
        self._schedule_idle()
        self.async_update_listeners()
