"""Config flow for Parcel Tracker."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ParcelTrackerApiClient, ParcelTrackerApiError, ParcelTrackerAuthError
from .const import CONF_API_KEY, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})


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
