"""Services for the Parcel Tracker integration."""

from __future__ import annotations

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN

SERVICE_ADD = "add"
SERVICE_REMOVE = "remove"
SERVICE_REFRESH = "refresh"
SERVICE_ARCHIVE = "archive"
SERVICE_GET_HISTORY = "get_history"

ADD_SCHEMA = vol.Schema(
    {
        vol.Required("tracking_number"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("notes"): cv.string,
    }
)
PARCEL_ID_SCHEMA = vol.Schema({vol.Required("parcel_id"): cv.string})
GET_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("month"): cv.positive_int,
        vol.Optional("year"): cv.positive_int,
        vol.Optional("carrier"): cv.string,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the parcel_tracker services."""

    async def async_add(call: ServiceCall) -> None:
        """Add a new parcel to track."""

    async def async_remove(call: ServiceCall) -> None:
        """Permanently remove a tracked parcel."""

    async def async_refresh(call: ServiceCall) -> None:
        """Force an immediate refresh of all active parcels."""

    async def async_archive(call: ServiceCall) -> None:
        """Archive a delivered parcel."""

    async def async_get_history(call: ServiceCall) -> None:
        """Return parcel history, filterable by month, year and carrier."""

    hass.services.async_register(DOMAIN, SERVICE_ADD, async_add, schema=ADD_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE, async_remove, schema=PARCEL_ID_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, async_refresh)
    hass.services.async_register(
        DOMAIN, SERVICE_ARCHIVE, async_archive, schema=PARCEL_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_HISTORY, async_get_history, schema=GET_HISTORY_SCHEMA
    )
