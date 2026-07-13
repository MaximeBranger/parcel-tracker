"""Services for the Parcel Tracker integration."""

from __future__ import annotations

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .const import ALL_CARRIERS, CARRIER_LAPOSTE, DOMAIN
from .coordinator import ParcelNotFoundError, ParcelTrackerCoordinator

SERVICE_ADD = "add"
SERVICE_UPDATE = "update"
SERVICE_REMOVE = "remove"
SERVICE_REFRESH = "refresh"
SERVICE_ARCHIVE = "archive"
SERVICE_GET_HISTORY = "get_history"
SERVICE_GET_CONFIGURED_CARRIERS = "get_configured_carriers"

ADD_SCHEMA = vol.Schema(
    {
        vol.Required("tracking_number"): cv.string,
        vol.Optional("carrier", default=CARRIER_LAPOSTE): vol.In(ALL_CARRIERS),
        vol.Optional("name", default=""): cv.string,
        vol.Optional("notes", default=""): cv.string,
    }
)
UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required("parcel_id"): cv.string,
        vol.Optional("tracking_number"): cv.string,
        vol.Optional("carrier"): vol.In(ALL_CARRIERS),
        vol.Optional("name"): cv.string,
        vol.Optional("notes"): cv.string,
    }
)
PARCEL_ID_SCHEMA = vol.Schema({vol.Required("parcel_id"): cv.string})
GET_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("month"): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
        vol.Optional("year"): cv.positive_int,
        vol.Optional("carrier"): cv.string,
    }
)


def _get_coordinator(hass: HomeAssistant) -> ParcelTrackerCoordinator:
    """Return the single Parcel Tracker coordinator.

    The MVP only ever has one config entry (SPECIFICATIONS.md), so services
    are not entry-scoped.
    """
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError("Parcel Tracker is not configured")
    return next(iter(coordinators.values()))


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the parcel_tracker services."""

    async def async_add(call: ServiceCall) -> ServiceResponse:
        """Add a new parcel to track.

        The initial carrier lookup runs synchronously as part of this call
        (see ParcelTrackerCoordinator.async_add_parcel), so any lookup
        failure is already known by the time this returns — report it
        directly in the response rather than relying on callers to also
        catch the `parcel_error` event, which fires before they can
        possibly have subscribed to it.
        """
        coordinator = _get_coordinator(hass)
        parcel = await coordinator.async_add_parcel(
            tracking_number=call.data["tracking_number"],
            carrier=call.data["carrier"],
            name=call.data["name"],
            notes=call.data["notes"],
        )
        return {"error": parcel.last_error}

    async def async_update(call: ServiceCall) -> ServiceResponse:
        """Edit a tracked parcel's name, notes and/or tracking number."""
        coordinator = _get_coordinator(hass)
        try:
            parcel = await coordinator.async_update_parcel(
                call.data["parcel_id"],
                tracking_number=call.data.get("tracking_number"),
                carrier=call.data.get("carrier"),
                name=call.data.get("name"),
                notes=call.data.get("notes"),
            )
        except ParcelNotFoundError as err:
            raise HomeAssistantError(str(err)) from err
        return {"error": parcel.last_error}

    async def async_remove(call: ServiceCall) -> None:
        """Permanently remove a tracked parcel."""
        coordinator = _get_coordinator(hass)
        try:
            await coordinator.async_remove_parcel(call.data["parcel_id"])
        except ParcelNotFoundError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_refresh(call: ServiceCall) -> None:
        """Force an immediate refresh of all active parcels."""
        coordinator = _get_coordinator(hass)
        await coordinator.async_refresh()

    async def async_archive(call: ServiceCall) -> None:
        """Archive a delivered parcel."""
        coordinator = _get_coordinator(hass)
        try:
            await coordinator.async_archive_parcel(call.data["parcel_id"])
        except ParcelNotFoundError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_get_history(call: ServiceCall) -> ServiceResponse:
        """Return parcel history, filterable by month, year and carrier."""
        coordinator = _get_coordinator(hass)
        return {
            "parcels": coordinator.async_get_history(
                month=call.data.get("month"),
                year=call.data.get("year"),
                carrier=call.data.get("carrier"),
            )
        }

    async def async_get_configured_carriers(call: ServiceCall) -> ServiceResponse:
        """Return the carriers with credentials configured on this entry.

        Lets frontends (e.g. the parcel_tracker-card add/edit form) scope
        their carrier picker without access to the config entry's data,
        the same way ParcelTrackerOptionsFlow scopes its own form.
        """
        coordinator = _get_coordinator(hass)
        return {"carriers": list(coordinator.providers)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD,
        async_add,
        schema=ADD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE,
        async_update,
        schema=UPDATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE, async_remove, schema=PARCEL_ID_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, async_refresh)
    hass.services.async_register(
        DOMAIN, SERVICE_ARCHIVE, async_archive, schema=PARCEL_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HISTORY,
        async_get_history,
        schema=GET_HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CONFIGURED_CARRIERS,
        async_get_configured_carriers,
        supports_response=SupportsResponse.ONLY,
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove all parcel_tracker services (last config entry unloaded)."""
    for service in (
        SERVICE_ADD,
        SERVICE_UPDATE,
        SERVICE_REMOVE,
        SERVICE_REFRESH,
        SERVICE_ARCHIVE,
        SERVICE_GET_HISTORY,
        SERVICE_GET_CONFIGURED_CARRIERS,
    ):
        hass.services.async_remove(DOMAIN, service)
