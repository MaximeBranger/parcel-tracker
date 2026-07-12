"""DataUpdateCoordinator for Parcel Tracker."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import (
    ParcelTrackerApiClient,
    ParcelTrackerApiError,
    ParcelTrackerAuthError,
)
from .const import (
    CONF_API_KEY,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_PARCEL_ADDED,
    EVENT_PARCEL_DELIVERED,
    EVENT_PARCEL_ERROR,
    EVENT_PARCEL_REMOVED,
    EVENT_PARCEL_UPDATED,
    SIGNAL_PARCEL_ADDED,
    SIGNAL_PARCEL_REMOVED,
    STATUS_DELAYED,
    STATUS_DELIVERED,
    STATUS_RETURNED_TO_SENDER,
)
from .parcel import Parcel
from .storage import ParcelStorage

_LOGGER = logging.getLogger(__name__)

TERMINAL_STATUSES = {STATUS_DELIVERED, STATUS_RETURNED_TO_SENDER}


class ParcelNotFoundError(Exception):
    """Raised when a service call references an unknown parcel_id."""


class ParcelTrackerCoordinator(DataUpdateCoordinator[dict[str, Parcel]]):
    """Coordinate updates for all tracked, non-archived parcels.

    Parcels are managed dynamically through services (add/remove/archive),
    not through config flow steps, so this coordinator also owns the
    in-memory parcel list and its persistence rather than only fetching data.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.entry = entry
        self.api = ParcelTrackerApiClient(
            entry.data[CONF_API_KEY], async_get_clientsession(hass)
        )
        self.storage = ParcelStorage(hass)
        self._parcels: dict[str, Parcel] = {}

    @property
    def signal_added(self) -> str:
        """Dispatcher signal fired when a new active parcel entity is needed."""
        return SIGNAL_PARCEL_ADDED.format(entry_id=self.entry.entry_id)

    @property
    def signal_removed(self) -> str:
        """Dispatcher signal fired when a parcel entity should be dropped."""
        return SIGNAL_PARCEL_REMOVED.format(entry_id=self.entry.entry_id)

    async def _async_update_data(self) -> dict[str, Parcel]:
        if not self._parcels:
            self._parcels = await self.storage.async_load()

        for parcel in self._parcels.values():
            if parcel.archived:
                continue
            await self._async_refresh_parcel(parcel)

        await self.storage.async_save(self._parcels)
        return self._parcels

    async def _async_refresh_parcel(self, parcel: Parcel) -> None:
        """Refresh a single parcel, isolating per-parcel provider errors."""
        try:
            result = await self.api.async_track(parcel.tracking_number)
        except ParcelTrackerAuthError as err:
            raise ConfigEntryAuthFailed("Invalid La Poste API key") from err
        except ParcelTrackerApiError as err:
            _LOGGER.warning(
                "Error refreshing parcel %s (%s): %s",
                parcel.display_name,
                parcel.tracking_number,
                err,
            )
            self.hass.bus.async_fire(
                EVENT_PARCEL_ERROR,
                {
                    "parcel_id": parcel.id,
                    "tracking_number": parcel.tracking_number,
                    "error": str(err),
                },
            )
            return

        previous_status = parcel.status
        previous_history_len = len(parcel.history)

        parcel.status = result["status"]
        parcel.history = result["history"]
        parcel.estimated_delivery = result["estimated_delivery"]
        parcel.last_location = result["last_location"]
        parcel.last_update = result["last_update"]
        parcel.tracking_url = result["tracking_url"]

        if self._is_overdue(parcel):
            parcel.status = STATUS_DELAYED

        if parcel.status == previous_status and len(parcel.history) == previous_history_len:
            return

        self.hass.bus.async_fire(
            EVENT_PARCEL_UPDATED,
            {
                "parcel_id": parcel.id,
                "status": parcel.status,
                "previous_status": previous_status,
            },
        )
        if parcel.status == STATUS_DELIVERED and previous_status != STATUS_DELIVERED:
            self.hass.bus.async_fire(
                EVENT_PARCEL_DELIVERED,
                {"parcel_id": parcel.id, "tracking_number": parcel.tracking_number},
            )

    @staticmethod
    def _is_overdue(parcel: Parcel) -> bool:
        """Derive the "Retard" status: La Poste has no such timeline step."""
        if parcel.status in TERMINAL_STATUSES or not parcel.estimated_delivery:
            return False
        try:
            estimated = datetime.fromisoformat(parcel.estimated_delivery)
        except ValueError:
            return False
        now = datetime.now(estimated.tzinfo or timezone.utc)
        return now > estimated

    # -- Lifecycle, called from services.py ---------------------------------

    async def async_add_parcel(
        self, tracking_number: str, name: str = "", notes: str = ""
    ) -> Parcel:
        """Add a new parcel and start tracking it immediately."""
        parcel = Parcel(
            tracking_number=tracking_number,
            name=name,
            notes=notes,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._parcels[parcel.id] = parcel
        await self._async_refresh_parcel(parcel)
        await self.storage.async_save(self._parcels)

        self.async_set_updated_data(self._parcels)
        async_dispatcher_send(self.hass, self.signal_added, parcel.id)
        self.hass.bus.async_fire(
            EVENT_PARCEL_ADDED,
            {"parcel_id": parcel.id, "tracking_number": parcel.tracking_number},
        )
        return parcel

    async def async_remove_parcel(self, parcel_id: str) -> None:
        """Permanently remove a tracked parcel and its entity."""
        parcel = self._get_parcel(parcel_id)
        del self._parcels[parcel_id]
        await self.storage.async_save(self._parcels)

        self.async_set_updated_data(self._parcels)
        async_dispatcher_send(self.hass, self.signal_removed, parcel_id)
        self._async_remove_registry_entry(parcel_id)
        self.hass.bus.async_fire(
            EVENT_PARCEL_REMOVED,
            {"parcel_id": parcel.id, "tracking_number": parcel.tracking_number},
        )

    async def async_archive_parcel(self, parcel_id: str) -> None:
        """Archive a parcel: keep its data and entity, drop it from active sensors."""
        parcel = self._get_parcel(parcel_id)
        parcel.archived = True
        await self.storage.async_save(self._parcels)

        self.async_set_updated_data(self._parcels)
        async_dispatcher_send(self.hass, self.signal_removed, parcel_id)

    def async_get_history(
        self,
        month: int | None = None,
        year: int | None = None,
        carrier: str | None = None,
    ) -> list[dict]:
        """Return stored parcels (active and archived), optionally filtered."""
        parcels = list(self._parcels.values())
        if carrier:
            parcels = [p for p in parcels if p.carrier == carrier]
        if month or year:
            parcels = [p for p in parcels if self._matches_period(p, month, year)]
        return [p.to_dict() for p in parcels]

    @staticmethod
    def _matches_period(parcel: Parcel, month: int | None, year: int | None) -> bool:
        if not parcel.created_at:
            return False
        try:
            created = datetime.fromisoformat(parcel.created_at)
        except ValueError:
            return False
        if year and created.year != year:
            return False
        if month and created.month != month:
            return False
        return True

    def _get_parcel(self, parcel_id: str) -> Parcel:
        try:
            return self._parcels[parcel_id]
        except KeyError as err:
            raise ParcelNotFoundError(f"Unknown parcel_id: {parcel_id}") from err

    def _async_remove_registry_entry(self, parcel_id: str) -> None:
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, parcel_id)
        if entity_id:
            registry.async_remove(entity_id)
