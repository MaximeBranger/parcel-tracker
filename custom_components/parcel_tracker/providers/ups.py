"""API client for the UPS Track API (OAuth2 client_credentials)."""

from __future__ import annotations

import base64
import logging
import time
import uuid
from typing import Any

import aiohttp

from ..const import (
    CARRIER_UPS,
    STATUS_CREATED,
    STATUS_DELIVERED,
    STATUS_IN_TRANSIT,
    STATUS_INCIDENT,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_RETURNED_TO_SENDER,
    STATUS_TAKEN_IN_CHARGE,
)
from .base import (
    ParcelTrackerApiError,
    ParcelTrackerAuthError,
    ParcelTrackerNotFoundError,
    TrackingProvider,
)

_LOGGER = logging.getLogger(__name__)

OAUTH_URL = "https://onlinetools.ups.com/security/v1/oauth/token"
TRACK_URL = "https://onlinetools.ups.com/api/track/v1/details/{tracking_number}"
PUBLIC_TRACKING_URL = (
    "https://www.ups.com/track?tracknum={tracking_number}"
)

# UPS's documented test tracking number, always resolved by their sandbox.
TEST_TRACKING_NUMBER = "1Z12345E0291980793"

# UPS's `activity[].status.type` is a short, documented enum of milestone
# types. Finer sub-states (e.g. out for delivery) are detected from the
# free-text description — refine from real responses (see README).
STATUS_TYPE_MAP: dict[str, str] = {
    "M": STATUS_CREATED,
    "P": STATUS_TAKEN_IN_CHARGE,
    "I": STATUS_IN_TRANSIT,
    "D": STATUS_DELIVERED,
    "X": STATUS_INCIDENT,
    "RS": STATUS_RETURNED_TO_SENDER,
}
DESCRIPTION_STATUS_MAP: dict[str, str] = {
    "out for delivery": STATUS_OUT_FOR_DELIVERY,
    "delivered": STATUS_DELIVERED,
    "exception": STATUS_INCIDENT,
    "returned to shipper": STATUS_RETURNED_TO_SENDER,
}

TOKEN_EXPIRY_MARGIN_SECONDS = 60


class UpsProvider(TrackingProvider):
    """Client for UPS's Track API v1."""

    carrier = CARRIER_UPS

    def __init__(
        self, client_id: str, client_secret: str, session: aiohttp.ClientSession
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def async_validate_credentials(self) -> None:
        """Raise if the configured client_id/client_secret are rejected."""
        await self.async_track(TEST_TRACKING_NUMBER)

    async def _async_get_token(self) -> str:
        """Return a cached OAuth token, requesting a new one once expired."""
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        basic_auth = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        async with self._session.post(
            OAUTH_URL,
            headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
        ) as response:
            if response.status == 401:
                raise ParcelTrackerAuthError("Invalid UPS client_id/client_secret")
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"UPS OAuth endpoint returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        token = payload.get("access_token")
        if not token:
            raise ParcelTrackerAuthError("Invalid UPS client_id/client_secret")

        self._token = token
        self._token_expires_at = time.monotonic() + max(
            int(payload.get("expires_in", 0)) - TOKEN_EXPIRY_MARGIN_SECONDS, 0
        )
        return token

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        token = await self._async_get_token()

        async with self._session.get(
            TRACK_URL.format(tracking_number=tracking_number),
            headers={
                "Authorization": f"Bearer {token}",
                "transId": str(uuid.uuid4()),
                "transactionSrc": "parcel_tracker_ha",
            },
        ) as response:
            if response.status == 401:
                self._token = None
                raise ParcelTrackerAuthError("Invalid UPS client_id/client_secret")
            if response.status == 404:
                raise ParcelTrackerNotFoundError(
                    f"Unknown tracking number: {tracking_number}"
                )
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"UPS Track API returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        if (payload.get("response") or {}).get("errors"):
            raise ParcelTrackerNotFoundError(
                f"Unknown tracking number: {tracking_number}"
            )

        shipments = payload.get("trackResponse", {}).get("shipment") or []
        packages = shipments[0].get("package") if shipments else None
        if not packages:
            raise ParcelTrackerNotFoundError(
                f"Unknown tracking number: {tracking_number}"
            )

        return self._normalize(tracking_number, packages[0])

    def _normalize(self, tracking_number: str, package: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw `package[0]` object into our internal parcel fields."""
        activities = package.get("activity") or []
        history = sorted(
            (
                {
                    "date": self._combine_date_time(event.get("date"), event.get("time")),
                    "label": (event.get("status") or {}).get("description"),
                    "location": self._format_location(event.get("location")),
                }
                for event in activities
                if event.get("date")
            ),
            key=lambda item: item["date"] or "",
        )
        last_event = history[-1] if history else None

        estimated_delivery = None
        for entry in package.get("deliveryDate") or []:
            estimated_delivery = entry.get("date") or estimated_delivery

        return {
            "status": self._status_from_current_status(package.get("currentStatus") or {}),
            "history": history,
            "estimated_delivery": estimated_delivery,
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else None,
            "tracking_url": PUBLIC_TRACKING_URL.format(tracking_number=tracking_number),
        }

    @staticmethod
    def _combine_date_time(date: str | None, time_: str | None) -> str | None:
        if not date:
            return None
        return f"{date}T{time_}" if time_ else date

    @staticmethod
    def _format_location(location: dict[str, Any] | None) -> str | None:
        if not location:
            return None
        address = location.get("address") or {}
        parts = [address.get("city"), address.get("stateProvince"), address.get("countryCode")]
        return ", ".join(part for part in parts if part) or None

    @classmethod
    def _status_from_current_status(cls, current_status: dict[str, Any]) -> str:
        description = (current_status.get("description") or "").strip().lower()
        for known, mapped in DESCRIPTION_STATUS_MAP.items():
            if known in description:
                return mapped

        status_type = current_status.get("type")
        if status_type in STATUS_TYPE_MAP:
            return STATUS_TYPE_MAP[status_type]

        _LOGGER.debug(
            "Unrecognized UPS status (type=%r, description=%r), defaulting to in_transit",
            status_type,
            description,
        )
        return STATUS_IN_TRANSIT
