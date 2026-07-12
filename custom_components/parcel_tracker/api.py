"""API client for the La Poste tracking provider."""

from __future__ import annotations

import aiohttp

API_BASE_URL = "https://api.laposte.fr/suivi/v2/idships"


class ParcelTrackerApiClient:
    """Minimal client for the La Poste Suivi API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def async_track(self, tracking_number: str) -> dict:
        """Fetch the tracking status for a single parcel."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_BASE_URL}/{tracking_number}",
                headers={"X-Okapi-Key": self._api_key},
            ) as response:
                response.raise_for_status()
                return await response.json()
