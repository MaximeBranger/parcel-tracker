"""API client for the La Poste tracking provider."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    STATUS_AT_SORTING_CENTER,
    STATUS_CREATED,
    STATUS_DELIVERED,
    STATUS_IN_TRANSIT,
    STATUS_INCIDENT,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_RETURNED_TO_SENDER,
    STATUS_TAKEN_IN_CHARGE,
)

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://api.laposte.fr/suivi/v2/idships"
PUBLIC_TRACKING_URL = (
    "https://www.laposte.fr/outils/suivre-vos-envois?code={tracking_number}"
)

# A tracking number La Poste documents as always returning a valid dummy
# response, used to validate an API key without tracking a real parcel.
TEST_TRACKING_NUMBER = "8Q00000000000"

# La Poste's `timeline` exposes a small, stable set of macro delivery steps
# (unlike the much larger and undocumented `event` code list). We match on
# the French `shortLabel` of the last reached step. Unrecognized labels fall
# back to STATUS_IN_TRANSIT and are logged, so the mapping can be extended
# from real responses observed during dev testing (see README).
TIMELINE_STATUS_MAP: dict[str, str] = {
    "pris en charge": STATUS_TAKEN_IN_CHARGE,
    "en cours de traitement": STATUS_AT_SORTING_CENTER,
    "traitement": STATUS_AT_SORTING_CENTER,
    "en cours d'acheminement": STATUS_IN_TRANSIT,
    "acheminement": STATUS_IN_TRANSIT,
    "en cours de livraison": STATUS_OUT_FOR_DELIVERY,
    "livraison en cours": STATUS_OUT_FOR_DELIVERY,
    "livré": STATUS_DELIVERED,
    "distribué": STATUS_DELIVERED,
    "anomalie": STATUS_INCIDENT,
    "incident": STATUS_INCIDENT,
    "retour expéditeur": STATUS_RETURNED_TO_SENDER,
    "retourné": STATUS_RETURNED_TO_SENDER,
}


class ParcelTrackerApiError(Exception):
    """Base error for the La Poste API client."""


class ParcelTrackerAuthError(ParcelTrackerApiError):
    """Raised when the API key is rejected."""


class ParcelTrackerNotFoundError(ParcelTrackerApiError):
    """Raised when the tracking number is unknown to the provider."""


class ParcelTrackerApiClient:
    """Minimal client for the La Poste Suivi API."""

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    async def async_validate_api_key(self) -> None:
        """Raise if the configured API key is rejected by La Poste."""
        await self.async_track(TEST_TRACKING_NUMBER)

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        async with self._session.get(
            f"{API_BASE_URL}/{tracking_number}",
            headers={"X-Okapi-Key": self._api_key},
            params={"lang": "fr_FR"},
        ) as response:
            if response.status == 401:
                raise ParcelTrackerAuthError("Invalid La Poste API key")
            if response.status == 404:
                raise ParcelTrackerNotFoundError(
                    f"Unknown tracking number: {tracking_number}"
                )
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"La Poste API returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        return_code = payload.get("returnCode", response.status)
        if return_code == 401:
            raise ParcelTrackerAuthError("Invalid La Poste API key")
        if return_code == 404:
            raise ParcelTrackerNotFoundError(
                f"Unknown tracking number: {tracking_number}"
            )

        shipment = payload.get("shipment") or {}
        return self._normalize(tracking_number, shipment)

    def _normalize(
        self, tracking_number: str, shipment: dict[str, Any]
    ) -> dict[str, Any]:
        """Turn a raw `shipment` object into our internal parcel fields."""
        timeline = shipment.get("timeline") or []
        events = shipment.get("event") or []

        history = sorted(
            (
                {
                    "date": event.get("date"),
                    "label": event.get("label"),
                    "location": event.get("location"),
                }
                for event in events
                if event.get("date")
            ),
            key=lambda item: item["date"],
        )
        last_event = history[-1] if history else None

        return {
            "status": self._status_from_timeline(timeline),
            "history": history,
            "estimated_delivery": shipment.get("deliveryDate"),
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else None,
            "tracking_url": shipment.get("url")
            or PUBLIC_TRACKING_URL.format(tracking_number=tracking_number),
        }

    @staticmethod
    def _status_from_timeline(timeline: list[dict[str, Any]]) -> str:
        """Map the last reached timeline step to an internal status."""
        reached = [step for step in timeline if step.get("status")]
        if not reached:
            return STATUS_CREATED

        label = (reached[-1].get("shortLabel") or "").strip().lower()
        for known_label, status in TIMELINE_STATUS_MAP.items():
            if known_label in label:
                return status

        _LOGGER.debug(
            "Unrecognized La Poste timeline label %r, defaulting to in_transit",
            label,
        )
        return STATUS_IN_TRANSIT
