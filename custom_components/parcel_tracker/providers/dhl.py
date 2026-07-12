"""API client for the DHL Unified Tracking API."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from ..const import (
    CARRIER_DHL,
    STATUS_CREATED,
    STATUS_DELIVERED,
    STATUS_IN_TRANSIT,
    STATUS_INCIDENT,
    STATUS_OUT_FOR_DELIVERY,
)
from .base import (
    ParcelTrackerApiError,
    ParcelTrackerAuthError,
    ParcelTrackerNotFoundError,
    TrackingProvider,
)

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://api-eu.dhl.com/track/shipments"
PUBLIC_TRACKING_URL = (
    "https://www.dhl.com/en/express/tracking.html?AWB={tracking_number}"
)

# DHL's own test tracking number, documented to return a fixed dummy
# "delivered" shipment against their production tracking endpoint.
TEST_TRACKING_NUMBER = "00340434292135100600"

# DHL's `status.statusCode` is a coarse, documented enum with only five
# values, so out-of-transit sub-states (at sorting center / out for
# delivery) are derived from the free-text `description` — refine this
# mapping from real responses observed during dev testing (see README).
STATUS_CODE_MAP: dict[str, str] = {
    "pre-transit": STATUS_CREATED,
    "transit": STATUS_IN_TRANSIT,
    "delivered": STATUS_DELIVERED,
    "failure": STATUS_INCIDENT,
}
DESCRIPTION_STATUS_MAP: dict[str, str] = {
    "out for delivery": STATUS_OUT_FOR_DELIVERY,
    "with delivery courier": STATUS_OUT_FOR_DELIVERY,
    "delivered": STATUS_DELIVERED,
    "exception": STATUS_INCIDENT,
    "delay": STATUS_INCIDENT,
    "clearance event": STATUS_INCIDENT,
}


class DhlProvider(TrackingProvider):
    """Client for DHL's Unified Tracking API."""

    carrier = CARRIER_DHL

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    async def async_validate_credentials(self) -> None:
        """Raise if the configured API key is rejected by DHL."""
        await self.async_track(TEST_TRACKING_NUMBER)

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        async with self._session.get(
            API_BASE_URL,
            headers={"DHL-API-Key": self._api_key},
            params={"trackingNumber": tracking_number},
        ) as response:
            if response.status == 401:
                raise ParcelTrackerAuthError("Invalid DHL API key")
            if response.status == 404:
                raise ParcelTrackerNotFoundError(
                    f"Unknown tracking number: {tracking_number}"
                )
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"DHL API returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        shipments = payload.get("shipments") or []
        if not shipments:
            raise ParcelTrackerNotFoundError(
                f"Unknown tracking number: {tracking_number}"
            )

        return self._normalize(tracking_number, shipments[0])

    def _normalize(self, tracking_number: str, shipment: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw `shipments[0]` object into our internal parcel fields."""
        events = shipment.get("events") or []
        history = sorted(
            (
                {
                    "date": event.get("timestamp"),
                    "label": event.get("description") or event.get("status"),
                    "location": self._format_location(event.get("location")),
                }
                for event in events
                if event.get("timestamp")
            ),
            key=lambda item: item["date"],
        )
        last_event = history[-1] if history else None
        status = shipment.get("status") or {}

        return {
            "status": self._status_from_status(status),
            "history": history,
            "estimated_delivery": shipment.get("estimatedTimeOfDelivery"),
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else None,
            "tracking_url": PUBLIC_TRACKING_URL.format(tracking_number=tracking_number),
        }

    @staticmethod
    def _format_location(location: dict[str, Any] | None) -> str | None:
        if not location:
            return None
        return (location.get("address") or {}).get("addressLocality")

    @classmethod
    def _status_from_status(cls, status: dict[str, Any]) -> str:
        description = (status.get("description") or status.get("status") or "").strip().lower()
        for known, mapped in DESCRIPTION_STATUS_MAP.items():
            if known in description:
                return mapped

        status_code = (status.get("statusCode") or "").strip().lower()
        if status_code in STATUS_CODE_MAP:
            return STATUS_CODE_MAP[status_code]

        _LOGGER.debug(
            "Unrecognized DHL status (code=%r, description=%r), defaulting to in_transit",
            status_code,
            description,
        )
        return STATUS_IN_TRANSIT
