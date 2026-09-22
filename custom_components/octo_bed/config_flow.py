"""Setup: the bed is found over Bluetooth, asked what it has, and unlocked."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import octo_bed_protocol as protocol
import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import OctoBedConfigEntry
from .const import (
    ADVERTISED_SERVICE_UUID,
    CONF_FEATURES,
    CONF_IDLE_TIMEOUT,
    CONF_KEEPALIVE_INTERVAL,
    CONF_MOVE_STEPS,
    CONF_PIN,
    CONF_POSITION_STEPS,
    CONF_STEP_INTERVAL,
    DEFAULTS,
    DOMAIN,
    LIMITS,
    NAME_PREFIXES,
    SERVICE_UUID,
)
from .coordinator import PinRejectedError, async_probe, features_to_data

_LOGGER = logging.getLogger(__name__)

PIN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
PIN_SCHEMA = vol.Schema({vol.Required(CONF_PIN): PIN_SELECTOR})

TIMINGS = (
    CONF_STEP_INTERVAL,
    CONF_MOVE_STEPS,
    CONF_POSITION_STEPS,
    CONF_IDLE_TIMEOUT,
    CONF_KEEPALIVE_INTERVAL,
)


def is_octo(info: BluetoothServiceInfoBleak) -> bool:
    """Tell an Octo receiver from the other beds that use service FFE0."""
    uuids = {uuid.lower() for uuid in info.service_uuids}
    if ADVERTISED_SERVICE_UUID in uuids:
        return True
    return SERVICE_UUID in uuids and (info.name or "").upper().startswith(NAME_PREFIXES)


def suggested_title(info: BluetoothServiceInfoBleak) -> str:
    """Name the bed after its receiver and the end of its address.

    Two receivers in one bed frame advertise the same name, so the address is
    what tells them apart until the user renames the entry.
    """
    suffix = info.address[-5:].replace(":", "")
    name = info.name or ""
    if name.isprintable() and name.upper().startswith(NAME_PREFIXES):
        return f"{name} {suffix}"
    return f"Octo {suffix}"


class OctoBedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for one bed."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._address: str | None = None
        self._title: str | None = None
        self._features: protocol.Features | None = None

    async def _async_probe(self, pin: str | None) -> str | None:
        """Talk to the bed. Returns an error key, or None on success."""
        assert self._address is not None
        try:
            self._features = await async_probe(
                self.hass, self._address, self._title or self._address, pin
            )
        except PinRejectedError:
            return "invalid_pin"
        except HomeAssistantError as err:
            return err.translation_key or "cannot_connect"
        except TimeoutError:
            # Connected, but the receiver never finished listing its features.
            return "no_features"
        except Exception:
            _LOGGER.exception("Unexpected error while talking to the bed")
            return "cannot_connect"
        if not self._features.motor_count and not self._features.has_light:
            return "no_features"
        return None

    def _create(self, pin: str | None) -> ConfigFlowResult:
        assert self._address is not None and self._features is not None
        data: dict[str, Any] = {
            CONF_ADDRESS: self._address,
            CONF_FEATURES: features_to_data(self._features),
        }
        if pin:
            data[CONF_PIN] = pin
        return self.async_create_entry(title=self._title or self._address, data=data)

    async def _async_probe_then_continue(
        self, step_id: str, schema: vol.Schema, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Probe without a PIN; ask for one only if the bed has one set."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await self._async_probe(None):
                errors["base"] = error
            else:
                assert self._features is not None
                if self._features.pin_set:
                    return await self.async_step_pin()
                return self._create(None)
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
            description_placeholders={"name": self._title or ""},
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a bed discovered over Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not is_octo(discovery_info):
            return self.async_abort(reason="not_supported")
        self._address = discovery_info.address
        self._title = suggested_title(discovery_info)
        self.context["title_placeholders"] = {"name": self._title}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then talk to the bed."""
        self._set_confirm_only()
        return await self._async_probe_then_continue(
            "bluetooth_confirm", vol.Schema({}), user_input
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick from the beds in range."""
        configured = self._async_current_ids(include_ignore=False)
        candidates = {
            info.address: suggested_title(info)
            for info in async_discovered_service_info(self.hass, connectable=True)
            if is_octo(info) and info.address not in configured
        }
        if not candidates:
            return self.async_abort(reason="no_devices_found")

        schema = vol.Schema({vol.Required(CONF_ADDRESS): vol.In(candidates)})
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._title = candidates[self._address]
        return await self._async_probe_then_continue("user", schema, user_input)

    async def async_step_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the PIN the bed has set, and try it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            pin = user_input[CONF_PIN]
            if error := _pin_format_error(pin) or await self._async_probe(pin):
                errors["base"] = error
            else:
                return self._create(pin)
        return self.async_show_form(
            step_id="pin",
            data_schema=PIN_SCHEMA,
            errors=errors,
            description_placeholders={"name": self._title or ""},
        )

    async def _async_release(self, entry: OctoBedConfigEntry) -> None:
        """Hang up a running entry's connection; the bed takes only one."""
        if entry.state is ConfigEntryState.LOADED:
            await entry.runtime_data.async_disconnect()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a PIN the bed no longer accepts."""
        self._address = entry_data[CONF_ADDRESS]
        self._title = self._get_reauth_entry().title
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the PIN again."""
        errors: dict[str, str] = {}
        if user_input is not None:
            pin = user_input[CONF_PIN]
            entry = self._get_reauth_entry()
            await self._async_release(entry)
            if error := _pin_format_error(pin) or await self._async_probe(pin):
                errors["base"] = error
            else:
                assert self._features is not None
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PIN: pin,
                        CONF_FEATURES: features_to_data(self._features),
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=PIN_SCHEMA,
            errors=errors,
            description_placeholders={"name": self._title or ""},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the bed again what it has, and change the PIN if need be.

        What the receiver reports decides which entities exist, so this is
        how a bed that gained a light or a memory slot gets them.
        """
        entry = self._get_reconfigure_entry()
        self._address = entry.data[CONF_ADDRESS]
        self._title = entry.title
        errors: dict[str, str] = {}
        if user_input is not None:
            pin = user_input.get(CONF_PIN) or None
            await self._async_release(entry)
            if error := (pin and _pin_format_error(pin)) or await self._async_probe(
                pin
            ):
                errors["base"] = error
            else:
                assert self._features is not None
                if self._features.pin_set and not pin:
                    errors["base"] = "pin_required"
                else:
                    data = {
                        CONF_ADDRESS: self._address,
                        CONF_FEATURES: features_to_data(self._features),
                    }
                    if pin:
                        data[CONF_PIN] = pin
                    return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_PIN,
                        description={"suggested_value": entry.data.get(CONF_PIN)},
                    ): PIN_SELECTOR
                }
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: OctoBedConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return OctoBedOptionsFlow()


def _pin_format_error(pin: str) -> str | None:
    """Catch a PIN that cannot be right before connecting for it."""
    return None if len(pin) == 4 and pin.isdigit() else "invalid_pin_format"


class OctoBedOptionsFlow(OptionsFlow):
    """How movements are driven and how long a connection stays open."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the timings."""
        if user_input is not None:
            return self.async_create_entry(
                data={key: int(value) for key, value in user_input.items()}
            )

        options = self.config_entry.options
        schema: dict[Any, Any] = {}
        for key in TIMINGS:
            minimum, maximum, step = LIMITS[key]
            schema[vol.Required(key, default=options.get(key, DEFAULTS[key]))] = (
                NumberSelector(
                    NumberSelectorConfig(
                        min=minimum,
                        max=maximum,
                        step=step,
                        mode=NumberSelectorMode.BOX,
                    )
                )
            )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
