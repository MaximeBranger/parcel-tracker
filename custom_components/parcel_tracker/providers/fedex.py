"""API client for the FedEx Track API (OAuth2 client_credentials)."""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from ..const import (
    CARRIER_FEDEX,
    STATUS_AT_SORTING_CENTER,
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

OAUTH_URL = "https://apis.fedex.com/oauth/token"
TRACK_URL = "https://apis.fedex.com/track/v1/trackingnumbers"
PUBLIC_TRACKING_URL = (
    "https://www.fedex.com/fedextrack/?trknbr={tracking_number}"
)

# A well-known FedEx test tracking number documented to always resolve in
# their sandbox, used to validate credentials without tracking a real parcel.
TEST_TRACKING_NUMBER = "449044304137821"

# Track API's `derivedStatusCode` is a large, mostly-undocumented set (~50
# codes). We only hard-map the handful FedEx documents as stable milestones
# and otherwise fall back to keyword-matching `latestStatusDetail.description`
# (see README for how to extend this from real responses).
DERIVED_CODE_STATUS_MAP: dict[str, str] = {
    "PU": STATUS_TAKEN_IN_CHARGE,
    "IT": STATUS_IN_TRANSIT,
    "AR": STATUS_AT_SORTING_CENTER,
    "DP": STATUS_AT_SORTING_CENTER,
    "OD": STATUS_OUT_FOR_DELIVERY,
    "DL": STATUS_DELIVERED,
    "DE": STATUS_INCIDENT,
    "CA": STATUS_INCIDENT,
    "RS": STATUS_RETURNED_TO_SENDER,
}
DESCRIPTION_STATUS_MAP: dict[str, str] = {
    "delivered": STATUS_DELIVERED,
    "out for delivery": STATUS_OUT_FOR_DELIVERY,
    "on the way": STATUS_IN_TRANSIT,
    "in transit": STATUS_IN_TRANSIT,
    "at local facility": STATUS_AT_SORTING_CENTER,
    "arrived at": STATUS_AT_SORTING_CENTER,
    "departed": STATUS_AT_SORTING_CENTER,
    "picked up": STATUS_TAKEN_IN_CHARGE,
    "shipment information sent to fedex": STATUS_CREATED,
    "returned to shipper": STATUS_RETURNED_TO_SENDER,
    "exception": STATUS_INCIDENT,
    "delay": STATUS_INCIDENT,
}

# Refresh the OAuth token a bit early to avoid racing its expiry mid-request.
TOKEN_EXPIRY_MARGIN_SECONDS = 60


class FedExProvider(TrackingProvider):
    """Client for FedEx's Track API v1."""

    carrier = CARRIER_FEDEX

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

        async with self._session.post(
            OAUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        ) as response:
            if response.status == 401:
                raise ParcelTrackerAuthError("Invalid FedEx client_id/client_secret")
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"FedEx OAuth endpoint returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        token = payload.get("access_token")
        if not token:
            raise ParcelTrackerAuthError("Invalid FedEx client_id/client_secret")

        self._token = token
        self._token_expires_at = time.monotonic() + max(
            payload.get("expires_in", 0) - TOKEN_EXPIRY_MARGIN_SECONDS, 0
        )
        return token

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        token = await self._async_get_token()

        async with self._session.post(
            TRACK_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-locale": "en_US",
            },
            json={
                "includeDetailedScans": True,
                "trackingInfo": [{"trackingNumberInfo": {"trackingNumber": tracking_number}}],
            },
        ) as response:
            if response.status == 401:
                # A cached token can also expire server-side between calls.
                self._token = None
                raise ParcelTrackerAuthError("Invalid FedEx client_id/client_secret")
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"FedEx Track API returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        complete_results = payload.get("output", {}).get("completeTrackResults") or []
        if not complete_results:
            raise ParcelTrackerNotFoundError(
                f"Unknown tracking number: {tracking_number}"
            )
        track_results = complete_results[0].get("trackResults") or []
        if not track_results or track_results[0].get("error"):
            raise ParcelTrackerNotFoundError(
                f"Unknown tracking number: {tracking_number}"
            )

        return self._normalize(tracking_number, track_results[0])

    def _normalize(self, tracking_number: str, result: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw `trackResults[0]` object into our internal parcel fields."""
        scan_events = result.get("scanEvents") or []
        history = sorted(
            (
                {
                    "date": event.get("date"),
                    "label": event.get("eventDescription"),
                    "location": self._format_location(event.get("scanLocation")),
                }
                for event in scan_events
                if event.get("date")
            ),
            key=lambda item: item["date"],
        )
        last_event = history[-1] if history else None

        estimated_delivery = None
        for entry in result.get("dateAndTimes") or []:
            if entry.get("type") == "ESTIMATED_DELIVERY":
                estimated_delivery = entry.get("dateTime")

        return {
            "status": self._status_from_latest_detail(result.get("latestStatusDetail") or {}),
            "history": history,
            "estimated_delivery": estimated_delivery,
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else None,
            "tracking_url": PUBLIC_TRACKING_URL.format(tracking_number=tracking_number),
        }

    @staticmethod
    def _format_location(location: dict[str, Any] | None) -> str | None:
        if not location:
            return None
        parts = [
            location.get("city"),
            location.get("stateOrProvinceCode"),
            location.get("countryCode"),
        ]
        return ", ".join(part for part in parts if part) or None

    @classmethod
    def _status_from_latest_detail(cls, detail: dict[str, Any]) -> str:
        derived_code = detail.get("derivedCode") or detail.get("code")
        if derived_code in DERIVED_CODE_STATUS_MAP:
            return DERIVED_CODE_STATUS_MAP[derived_code]

        description = (detail.get("description") or detail.get("statusByLocale") or "").strip().lower()
        for known, status in DESCRIPTION_STATUS_MAP.items():
            if known in description:
                return status

        _LOGGER.debug(
            "Unrecognized FedEx status (code=%r, description=%r), defaulting to in_transit",
            derived_code,
            description,
        )
        return STATUS_IN_TRANSIT
