"""API client for GLS's official Track & Trace API v1.

Unlike DPD and Mondial Relay, this is a properly documented, self-service
API: sign up at https://dev-portal.gls-group.net, register an App and
subscribe it to "Track And Trace V1" to get a client_id/client_secret pair
(see README). Authentication is standard OAuth2 client_credentials against
Apigee. GLS's own OpenAPI spec states production and sandbox are identical
and to always use production, so there is no separate sandbox base URL here.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from ..const import (
    CARRIER_GLS,
    STATUS_AT_SORTING_CENTER,
    STATUS_CREATED,
    STATUS_DELIVERED,
    STATUS_IN_TRANSIT,
    STATUS_INCIDENT,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_TAKEN_IN_CHARGE,
)
from .base import (
    ParcelTrackerApiError,
    ParcelTrackerAuthError,
    ParcelTrackerNotFoundError,
    TrackingProvider,
)

_LOGGER = logging.getLogger(__name__)

OAUTH_URL = "https://api.gls-group.net/oauth2/v1/token"
TRACK_URL = "https://api.gls-group.net/track-and-trace-v1/tracking/simple/references/{reference}"
PUBLIC_TRACKING_URL = "https://gls-group.com/GROUP/en/parcel-tracking?match={tracking_number}"

# GLS's documented, always-live test parcel (see the Test Data Set table in
# the Track And Trace V1 OpenAPI spec) — used to validate credentials
# without depending on a real shipment.
TEST_TRACKING_NUMBER = "REF_0000001"

# Refresh the OAuth token a bit early to avoid racing its expiry mid-request.
TOKEN_EXPIRY_MARGIN_SECONDS = 60

# ParcelDTO.status is a documented, stable enum (unlike most other carriers
# here, which require guessing at free-text event labels).
STATUS_MAP: dict[str, str] = {
    "PLANNEDPICKUP": STATUS_CREATED,
    "PREADVICE": STATUS_CREATED,
    "INPICKUP": STATUS_TAKEN_IN_CHARGE,
    "NOTPICKEDUP": STATUS_INCIDENT,
    "INTRANSIT": STATUS_IN_TRANSIT,
    "INWAREHOUSE": STATUS_AT_SORTING_CENTER,
    "INDELIVERY": STATUS_OUT_FOR_DELIVERY,
    "DELIVEREDPS": STATUS_OUT_FOR_DELIVERY,
    "DELIVERED": STATUS_DELIVERED,
    "NOTDELIVERED": STATUS_INCIDENT,
    "CANCELED": STATUS_INCIDENT,
}


class GlsProvider(TrackingProvider):
    """Client for GLS's official Track And Trace API v1."""

    carrier = CARRIER_GLS

    def __init__(self, client_id: str, client_secret: str, session: aiohttp.ClientSession) -> None:
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

        async with self._session.post(
            OAUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        ) as response:
            if response.status in (400, 401):
                raise ParcelTrackerAuthError("Invalid GLS client_id/client_secret")
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"GLS OAuth endpoint returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        token = payload.get("access_token")
        if not token:
            raise ParcelTrackerAuthError("Invalid GLS client_id/client_secret")

        self._token = token
        self._token_expires_at = time.monotonic() + max(
            payload.get("expires_in", 0) - TOKEN_EXPIRY_MARGIN_SECONDS, 0
        )
        return token

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        token = await self._async_get_token()

        async with self._session.get(
            TRACK_URL.format(reference=tracking_number),
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            if response.status == 401:
                # A cached token can also expire server-side between calls.
                self._token = None
                raise ParcelTrackerAuthError("Invalid GLS client_id/client_secret")
            if response.status == 404:
                raise ParcelTrackerNotFoundError(f"Unknown tracking number: {tracking_number}")
            if response.status != 200:
                raise ParcelTrackerApiError(f"GLS API returned HTTP {response.status}")
            payload = await response.json(content_type=None)

        parcels = payload.get("parcels") or []
        parcel = next((p for p in parcels if not p.get("errorCode")), None)
        if parcel is None:
            raise ParcelTrackerNotFoundError(f"Unknown tracking number: {tracking_number}")

        return self._normalize(tracking_number, parcel)

    def _normalize(self, tracking_number: str, parcel: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw `parcels[]` entry into our internal parcel fields."""
        history = sorted(
            (
                {
                    "date": event.get("eventDateTime"),
                    "label": event.get("description"),
                    "location": self._format_location(event),
                }
                for event in parcel.get("events") or []
                if event.get("eventDateTime")
            ),
            key=lambda item: item["date"],
        )
        last_event = history[-1] if history else None

        return {
            "status": self._status_from_parcel(parcel),
            "history": history,
            "estimated_delivery": None,
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else parcel.get("statusDateTime"),
            "tracking_url": PUBLIC_TRACKING_URL.format(tracking_number=tracking_number),
        }

    @staticmethod
    def _format_location(event: dict[str, Any]) -> str | None:
        parts = [event.get("city"), event.get("country")]
        return ", ".join(part for part in parts if part) or None

    @classmethod
    def _status_from_parcel(cls, parcel: dict[str, Any]) -> str:
        status = (parcel.get("status") or "").strip().upper()
        if status in STATUS_MAP:
            return STATUS_MAP[status]

        _LOGGER.debug("Unrecognized GLS status %r, defaulting to in_transit", status)
        return STATUS_IN_TRANSIT
