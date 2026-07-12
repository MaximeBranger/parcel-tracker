"""API client for the PostNord Track & Trace API.

PostNord's `status` enum is not published in full anywhere public; only
`INFORMED`, `EN_ROUTE` and `DELIVERED` are confirmed from real API examples
(developer.postnord.com's own sample response). `AVAILABLE_FOR_DELIVERY` is
a best guess for parcel-shop pickup readiness, not a verified value —
refine `STATUS_CODE_MAP` from real responses observed during dev testing
(see README).
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from ..const import (
    CARRIER_POSTNORD,
    STATUS_CREATED,
    STATUS_DELAYED,
    STATUS_DELIVERED,
    STATUS_IN_TRANSIT,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_RETURNED_TO_SENDER,
)
from .base import (
    ParcelTrackerApiError,
    ParcelTrackerAuthError,
    ParcelTrackerNotFoundError,
    TrackingProvider,
)

_LOGGER = logging.getLogger(__name__)

API_URL = "https://api2.postnord.com/rest/shipment/v5/trackandtrace/findByIdentifier.json"
PUBLIC_TRACKING_URL = (
    "https://www.postnord.se/en/our-tools/track-and-trace/?id={tracking_number}"
)

# A well-formed but almost certainly unassigned Swedish parcel ID, used to
# validate an API key without depending on a real parcel (PostNord has no
# documented sandbox test number).
TEST_TRACKING_NUMBER = "00000000000000000SE"

STATUS_CODE_MAP: dict[str, str] = {
    "informed": STATUS_CREATED,
    "en_route": STATUS_IN_TRANSIT,
    "available_for_delivery": STATUS_OUT_FOR_DELIVERY,
    "delivered": STATUS_DELIVERED,
}
DESCRIPTION_STATUS_MAP: dict[str, str] = {
    "out for delivery": STATUS_OUT_FOR_DELIVERY,
    "ready for collection": STATUS_OUT_FOR_DELIVERY,
    "delivered": STATUS_DELIVERED,
    "delay": STATUS_DELAYED,
    "returned": STATUS_RETURNED_TO_SENDER,
}


class PostNordProvider(TrackingProvider):
    """Client for PostNord's Track & Trace `findByIdentifier` API."""

    carrier = CARRIER_POSTNORD

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    async def async_validate_credentials(self) -> None:
        """Raise if the configured API key is rejected by PostNord."""
        try:
            await self.async_track(TEST_TRACKING_NUMBER)
        except ParcelTrackerNotFoundError:
            return

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        async with self._session.get(
            API_URL,
            params={"id": tracking_number, "locale": "en", "apikey": self._api_key},
        ) as response:
            if response.status in (401, 403):
                raise ParcelTrackerAuthError("Invalid PostNord API key")
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"PostNord API returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        if payload.get("error"):
            raise ParcelTrackerApiError(f"PostNord API error: {payload['error']}")

        shipments = (payload.get("TrackingInformationResponse") or {}).get(
            "shipments"
        ) or []
        if not shipments:
            raise ParcelTrackerNotFoundError(
                f"Unknown tracking number: {tracking_number}"
            )

        return self._normalize(tracking_number, shipments[0])

    def _normalize(self, tracking_number: str, shipment: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw `shipments[0]` object into our internal parcel fields."""
        events = [
            event
            for item in shipment.get("items") or []
            for event in item.get("events") or []
        ]
        history = sorted(
            (
                {
                    "date": event.get("eventTime"),
                    "label": event.get("eventDescription"),
                    "location": self._format_location(event.get("location")),
                }
                for event in events
                if event.get("eventTime")
            ),
            key=lambda item: item["date"],
        )
        last_event = history[-1] if history else None

        return {
            "status": self._status_from_shipment(shipment),
            "history": history,
            "estimated_delivery": shipment.get("deliveryDate")
            or shipment.get("estimatedTimeOfArrival"),
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else None,
            "tracking_url": PUBLIC_TRACKING_URL.format(tracking_number=tracking_number),
        }

    @staticmethod
    def _format_location(location: dict[str, Any] | None) -> str | None:
        if not location:
            return None
        parts = [
            location.get("city") or location.get("name") or location.get("displayName"),
            location.get("country"),
        ]
        return ", ".join(part for part in parts if part) or None

    @classmethod
    def _status_from_shipment(cls, shipment: dict[str, Any]) -> str:
        description = (
            (shipment.get("statusText") or {}).get("header") or ""
        ).strip().lower()
        for known, mapped in DESCRIPTION_STATUS_MAP.items():
            if known in description:
                return mapped

        status_code = (shipment.get("status") or "").strip().lower()
        if status_code in STATUS_CODE_MAP:
            return STATUS_CODE_MAP[status_code]

        _LOGGER.debug(
            "Unrecognized PostNord status (code=%r, description=%r), defaulting to in_transit",
            status_code,
            description,
        )
        return STATUS_IN_TRANSIT
