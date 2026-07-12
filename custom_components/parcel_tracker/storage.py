"""Local persistence for tracked parcels."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .parcel import Parcel

STORAGE_KEY = "parcel_tracker"
STORAGE_VERSION = 1


class ParcelStorage:
    """Persist parcels to .storage/parcel_tracker."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_load(self) -> dict[str, Parcel]:
        """Load parcels from disk."""
        data = await self._store.async_load() or []
        parcels = (Parcel.from_dict(item) for item in data)
        return {parcel.id: parcel for parcel in parcels}

    async def async_save(self, parcels: dict[str, Parcel]) -> None:
        """Persist parcels to disk."""
        await self._store.async_save([parcel.to_dict() for parcel in parcels.values()])
