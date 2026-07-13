"""Config flow for Parcel Tracker."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CARRIER_LABELS,
    CONF_API_KEY,
    CONF_DHL_API_KEY,
    CONF_DPD_LOGIN,
    CONF_DPD_PASSWORD,
    CONF_FEDEX_CLIENT_ID,
    CONF_FEDEX_CLIENT_SECRET,
    CONF_MONDIAL_RELAY_LOGIN,
    CONF_MONDIAL_RELAY_PRIVATE_KEY,
    CONF_POSTNORD_API_KEY,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    DOMAIN,
)
from .coordinator import ParcelNotFoundError, ParcelTrackerCoordinator
from .providers import (
    CARRIER_CONFIG_KEYS,
    ParcelTrackerApiError,
    ParcelTrackerAuthError,
    build_provider,
    configured_carriers,
)

_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)

# Every carrier's credentials are optional here; async_step_user requires at
# least one to be filled in (see _async_validate_carriers). This lets a user
# configure only the carriers they actually receive parcels from. Secret
# values (API keys, client secrets, private keys) use a password selector so
# they aren't displayed in clear text in the UI; client IDs/logins are plain
# identifiers, not secrets, so they stay as regular text fields.
CARRIER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_API_KEY, default=""): _PASSWORD_SELECTOR,
        vol.Optional(CONF_FEDEX_CLIENT_ID, default=""): str,
        vol.Optional(CONF_FEDEX_CLIENT_SECRET, default=""): _PASSWORD_SELECTOR,
        vol.Optional(CONF_DHL_API_KEY, default=""): _PASSWORD_SELECTOR,
        vol.Optional(CONF_UPS_CLIENT_ID, default=""): str,
        vol.Optional(CONF_UPS_CLIENT_SECRET, default=""): _PASSWORD_SELECTOR,
        vol.Optional(CONF_MONDIAL_RELAY_LOGIN, default=""): str,
        vol.Optional(CONF_MONDIAL_RELAY_PRIVATE_KEY, default=""): _PASSWORD_SELECTOR,
        vol.Optional(CONF_POSTNORD_API_KEY, default=""): _PASSWORD_SELECTOR,
        vol.Optional(CONF_DPD_LOGIN, default=""): str,
        vol.Optional(CONF_DPD_PASSWORD, default=""): _PASSWORD_SELECTOR,
    }
)


def _parcel_fields_schema(carriers: list[str], *, default_carrier: str) -> vol.Schema:
    """Build the add/edit parcel form, scoped to the entry's configured carriers."""
    return vol.Schema(
        {
            vol.Required("tracking_number"): str,
            vol.Optional("carrier", default=default_carrier): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=carrier, label=CARRIER_LABELS[carrier])
                        for carrier in carriers
                    ]
                )
            ),
            vol.Optional("name", default=""): str,
            vol.Optional("notes", default=""): str,
        }
    )


class ParcelTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Parcel Tracker."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: entering carrier API credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            errors = await self._async_validate_carriers(user_input)
            if not errors:
                return self.async_create_entry(title="Parcel Tracker", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=CARRIER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauthentication when a carrier's credentials are rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user to fix carrier credentials and re-validate them."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._async_validate_carriers(user_input)
            if not errors:
                return self.async_update_reload_and_abort(reauth_entry, data=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                CARRIER_DATA_SCHEMA, reauth_entry.data
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user add or update carrier credentials after initial setup."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._async_validate_carriers(user_input)
            if not errors:
                return self.async_update_reload_and_abort(reconfigure_entry, data=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CARRIER_DATA_SCHEMA, reconfigure_entry.data
            ),
            errors=errors,
        )

    async def _async_validate_carriers(self, data: dict[str, Any]) -> dict[str, str]:
        """Call each carrier with credentials filled in to check they're accepted.

        Errors are keyed by that carrier's first config field, so the form
        highlights which carrier's credentials were rejected.
        """
        carriers = configured_carriers(data)
        if not carriers:
            return {"base": "at_least_one_required"}

        session = async_get_clientsession(self.hass)
        errors: dict[str, str] = {}
        for carrier in carriers:
            field = CARRIER_CONFIG_KEYS[carrier][0]
            provider = build_provider(carrier, data, session)
            try:
                await provider.async_validate_credentials()
            except ParcelTrackerAuthError:
                errors[field] = "invalid_auth"
            except aiohttp.ClientError:
                errors[field] = "cannot_connect"
            except ParcelTrackerApiError:
                errors[field] = "unknown"
        return errors

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ParcelTrackerOptionsFlow:
        """Return the options flow used to manage tracked parcels."""
        return ParcelTrackerOptionsFlow(config_entry)


class ParcelTrackerOptionsFlow(config_entries.OptionsFlow):
    """Manage tracked parcels from Settings → Devices & services → Configure.

    Parcels are not config entries — the single entry only ever holds carrier
    credentials (SPECIFICATIONS.md) — so this flow reads and mutates the
    coordinator's in-memory parcel list directly instead of storing config
    entry options.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._parcel_id: str | None = None

    @property
    def _coordinator(self) -> ParcelTrackerCoordinator:
        return self.hass.data[DOMAIN][self.config_entry.entry_id]

    @property
    def _configured_carriers(self) -> list[str]:
        """Carriers with credentials configured on this entry."""
        return list(self._coordinator.providers)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the top-level menu: add a parcel, or manage existing ones."""
        menu_options = ["add_parcel"]
        if any(not parcel.archived for parcel in self._coordinator.data.values()):
            menu_options.append("select_parcel")
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_add_parcel(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Track a new parcel."""
        if user_input is not None:
            await self._coordinator.async_add_parcel(
                tracking_number=user_input["tracking_number"],
                carrier=user_input["carrier"],
                name=user_input["name"],
                notes=user_input["notes"],
            )
            return await self.async_step_init()

        return self.async_show_form(
            step_id="add_parcel",
            data_schema=_parcel_fields_schema(
                self._configured_carriers, default_carrier=self._configured_carriers[0]
            ),
        )

    async def async_step_select_parcel(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick which active parcel to edit, archive or remove."""
        if user_input is not None:
            self._parcel_id = user_input["parcel_id"]
            return await self.async_step_parcel_menu()

        options = [
            selector.SelectOptionDict(
                value=parcel_id,
                label=f"{parcel.display_name} ({CARRIER_LABELS.get(parcel.carrier, parcel.carrier)} · {parcel.tracking_number})",
            )
            for parcel_id, parcel in self._coordinator.data.items()
            if not parcel.archived
        ]
        return self.async_show_form(
            step_id="select_parcel",
            data_schema=vol.Schema(
                {
                    vol.Required("parcel_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_parcel_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show what can be done with the parcel selected in the previous step."""
        try:
            parcel = self._selected_parcel()
        except ParcelNotFoundError:
            return await self.async_step_init()

        return self.async_show_menu(
            step_id="parcel_menu",
            menu_options=["edit_parcel", "archive_parcel", "remove_parcel", "init"],
            description_placeholders={"parcel_name": parcel.display_name},
        )

    async def async_step_edit_parcel(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the name, notes, carrier and/or tracking number of the selected parcel."""
        try:
            parcel = self._selected_parcel()
        except ParcelNotFoundError:
            return await self.async_step_init()

        if user_input is not None:
            await self._coordinator.async_update_parcel(
                parcel.id,
                tracking_number=user_input["tracking_number"],
                carrier=user_input["carrier"],
                name=user_input["name"],
                notes=user_input["notes"],
            )
            return await self.async_step_init()

        # Always offer the parcel's current carrier, even if its credentials
        # were since removed from the entry, so editing it doesn't force an
        # unrelated carrier change.
        carriers = self._configured_carriers
        if parcel.carrier not in carriers:
            carriers = [parcel.carrier, *carriers]

        return self.async_show_form(
            step_id="edit_parcel",
            data_schema=self.add_suggested_values_to_schema(
                _parcel_fields_schema(carriers, default_carrier=parcel.carrier),
                {
                    "tracking_number": parcel.tracking_number,
                    "carrier": parcel.carrier,
                    "name": parcel.name,
                    "notes": parcel.notes,
                },
            ),
            description_placeholders={"parcel_name": parcel.display_name},
        )

    async def async_step_archive_parcel(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm and archive the selected parcel."""
        try:
            parcel = self._selected_parcel()
        except ParcelNotFoundError:
            return await self.async_step_init()

        if user_input is not None:
            await self._coordinator.async_archive_parcel(parcel.id)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="archive_parcel",
            data_schema=vol.Schema({}),
            description_placeholders={"parcel_name": parcel.display_name},
        )

    async def async_step_remove_parcel(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm and permanently remove the selected parcel."""
        try:
            parcel = self._selected_parcel()
        except ParcelNotFoundError:
            return await self.async_step_init()

        if user_input is not None:
            await self._coordinator.async_remove_parcel(parcel.id)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="remove_parcel",
            data_schema=vol.Schema({}),
            description_placeholders={"parcel_name": parcel.display_name},
        )

    def _selected_parcel(self):
        """Return the parcel chosen in `select_parcel`, or raise if gone."""
        if self._parcel_id is None or self._parcel_id not in self._coordinator.data:
            raise ParcelNotFoundError(self._parcel_id)
        return self._coordinator.data[self._parcel_id]
