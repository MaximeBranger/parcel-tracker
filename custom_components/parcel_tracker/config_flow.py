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

from .api import ParcelTrackerApiClient, ParcelTrackerApiError, ParcelTrackerAuthError
from .const import CONF_API_KEY, DOMAIN
from .coordinator import ParcelNotFoundError, ParcelTrackerCoordinator

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})

PARCEL_FIELDS_SCHEMA = vol.Schema(
    {
        vol.Required("tracking_number"): str,
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
        """Handle the initial step: entering the La Poste API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            errors = await self._async_validate_api_key(user_input[CONF_API_KEY])
            if not errors:
                return self.async_create_entry(title="Parcel Tracker", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthentication when the API key is rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user for a new API key and re-validate it."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._async_validate_api_key(user_input[CONF_API_KEY])
            if not errors:
                reauth_entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    reauth_entry, data={**reauth_entry.data, **user_input}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _async_validate_api_key(self, api_key: str) -> dict[str, str]:
        """Call the La Poste API once to check the key is accepted."""
        session = async_get_clientsession(self.hass)
        client = ParcelTrackerApiClient(api_key, session)
        try:
            await client.async_validate_api_key()
        except ParcelTrackerAuthError:
            return {"base": "invalid_auth"}
        except aiohttp.ClientError:
            return {"base": "cannot_connect"}
        except ParcelTrackerApiError:
            return {"base": "unknown"}
        return {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ParcelTrackerOptionsFlow:
        """Return the options flow used to manage tracked parcels."""
        return ParcelTrackerOptionsFlow(config_entry)


class ParcelTrackerOptionsFlow(config_entries.OptionsFlow):
    """Manage tracked parcels from Settings → Devices & services → Configure.

    Parcels are not config entries — the single entry only ever holds the
    API key (SPECIFICATIONS.md) — so this flow reads and mutates the
    coordinator's in-memory parcel list directly instead of storing config
    entry options.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self.config_entry = config_entry
        self._parcel_id: str | None = None

    @property
    def _coordinator(self) -> ParcelTrackerCoordinator:
        return self.hass.data[DOMAIN][self.config_entry.entry_id]

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
                name=user_input["name"],
                notes=user_input["notes"],
            )
            return await self.async_step_init()

        return self.async_show_form(
            step_id="add_parcel", data_schema=PARCEL_FIELDS_SCHEMA
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
                label=f"{parcel.display_name} ({parcel.tracking_number})",
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
        """Edit the name, notes and/or tracking number of the selected parcel."""
        try:
            parcel = self._selected_parcel()
        except ParcelNotFoundError:
            return await self.async_step_init()

        if user_input is not None:
            await self._coordinator.async_update_parcel(
                parcel.id,
                tracking_number=user_input["tracking_number"],
                name=user_input["name"],
                notes=user_input["notes"],
            )
            return await self.async_step_init()

        return self.async_show_form(
            step_id="edit_parcel",
            data_schema=self.add_suggested_values_to_schema(
                PARCEL_FIELDS_SCHEMA,
                {
                    "tracking_number": parcel.tracking_number,
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
