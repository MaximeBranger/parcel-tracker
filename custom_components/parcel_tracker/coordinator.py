"""DataUpdateCoordinator for Parcel Tracker."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ParcelTrackerApiClient
from .const import DOMAIN
from .parcel import Parcel
from .storage import ParcelStorage

_LOGGER = logging.getLogger(__name__)

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=15)


class ParcelTrackerCoordinator(DataUpdateCoordinator[dict[str, Parcel]]):
    """Coordinate updates for all tracked, non-archived parcels."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.entry = entry
        self.api = ParcelTrackerApiClient(entry.data["api_key"])
        self.storage = ParcelStorage(hass)

    async def _async_update_data(self) -> dict[str, Parcel]:
        parcels = await self.storage.async_load()
        for parcel in parcels.values():
            if parcel.archived:
                continue
            result = await self.api.async_track(parcel.tracking_number)
            parcel.status = result.get("status", parcel.status)
        await self.storage.async_save(parcels)
        return parcels
