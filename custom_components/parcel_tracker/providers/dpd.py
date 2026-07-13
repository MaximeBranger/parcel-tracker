"""API client for the DPD Group professional "GeoService" web service.

Like Mondial Relay's WSI2, this is not a self-service developer API: DPD
only hands out `login`/`password` credentials and the GeoService WSDL/REST
contract to shippers under a professional DPD Group contract, so there is
no public sandbox to verify field names or status codes against. The
request shape below (`/login/{login}/{password}` returning a `geoSession`
token, then `/shipping/status/{tracking_number}` using that token) follows
the commonly-documented DPD Group "Toolbox" GeoService contract, but —
like the Mondial Relay WSI2 client — treat it as a best-effort starting
point to confirm against real professional credentials, not a verified
contract.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from ..const import (
    CARRIER_DPD,
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

API_BASE_URL = "https://api.dpd.com/geoservice"
LOGIN_URL = f"{API_BASE_URL}/login/{{login}}/{{password}}"
STATUS_URL = f"{API_BASE_URL}/shipping/status/{{tracking_number}}"
PUBLIC_TRACKING_URL = (
    "https://tracking.dpd.de/status/en_US/parcel/{tracking_number}"
)

# DPD Group sessions are documented elsewhere (WSI2-style contracts) as
# valid for roughly an hour; refresh a bit earlier to avoid racing expiry.
TOKEN_TTL_SECONDS = 55 * 60

LABEL_STATUS_MAP: dict[str, str] = {
    "pris en charge": STATUS_TAKEN_IN_CHARGE,
    "enlèvement": STATUS_TAKEN_IN_CHARGE,
    "en cours de transport": STATUS_IN_TRANSIT,
    "en transit": STATUS_IN_TRANSIT,
    "arrivée en agence": STATUS_AT_SORTING_CENTER,
    "arrivé au dépôt": STATUS_AT_SORTING_CENTER,
    "en cours de livraison": STATUS_OUT_FOR_DELIVERY,
    "en livraison": STATUS_OUT_FOR_DELIVERY,
    "livré": STATUS_DELIVERED,
    "distribué": STATUS_DELIVERED,
    "anomalie": STATUS_INCIDENT,
    "incident": STATUS_INCIDENT,
    "retour expéditeur": STATUS_RETURNED_TO_SENDER,
    "retourné": STATUS_RETURNED_TO_SENDER,
}


class DpdProvider(TrackingProvider):
    """Client for DPD Group's professional GeoService tracking web service."""

    carrier = CARRIER_DPD

    def __init__(self, login: str, password: str, session: aiohttp.ClientSession) -> None:
        self._login = login
        self._password = password
        self._session = session
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def async_validate_credentials(self) -> None:
        """Raise if the configured login/password are rejected by DPD."""
        await self._async_get_token()

    async def _async_get_token(self) -> str:
        """Return a cached geoSession token, logging in again once expired."""
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        async with self._session.get(
            LOGIN_URL.format(login=self._login, password=self._password)
        ) as response:
            if response.status in (401, 403):
                raise ParcelTrackerAuthError("Invalid DPD login/password")
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"DPD login endpoint returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        token = payload.get("geoSession") or payload.get("token")
        if not token:
            raise ParcelTrackerAuthError("Invalid DPD login/password")

        self._token = token
        self._token_expires_at = time.monotonic() + TOKEN_TTL_SECONDS
        return token

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        token = await self._async_get_token()

        async with self._session.get(
            STATUS_URL.format(tracking_number=tracking_number),
            headers={"geoSession": token},
        ) as response:
            if response.status == 401:
                self._token = None
                raise ParcelTrackerAuthError("Invalid DPD login/password")
            if response.status == 404:
                raise ParcelTrackerNotFoundError(
                    f"Unknown tracking number: {tracking_number}"
                )
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"DPD API returned HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        parcel = payload.get("parcel")
        if not parcel:
            raise ParcelTrackerNotFoundError(
                f"Unknown tracking number: {tracking_number}"
            )

        return self._normalize(tracking_number, parcel)

    def _normalize(self, tracking_number: str, parcel: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw `parcel` object into our internal parcel fields."""
        events = parcel.get("events") or []
        history = sorted(
            (
                {
                    "date": event.get("timestamp") or event.get("date"),
                    "label": event.get("label") or event.get("description"),
                    "location": event.get("location") or event.get("depot"),
                }
                for event in events
                if event.get("timestamp") or event.get("date")
            ),
            key=lambda item: item["date"] or "",
        )
        last_event = history[-1] if history else None

        return {
            "status": self._status_from_history(last_event),
            "history": history,
            "estimated_delivery": parcel.get("estimatedDeliveryDate"),
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else None,
            "tracking_url": PUBLIC_TRACKING_URL.format(tracking_number=tracking_number),
        }

    @classmethod
    def _status_from_history(cls, last_event: dict[str, Any] | None) -> str:
        if not last_event:
            return STATUS_CREATED

        label = (last_event.get("label") or "").strip().lower()
        for known_label, status in LABEL_STATUS_MAP.items():
            if known_label in label:
                return status

        _LOGGER.debug("Unrecognized DPD label %r, defaulting to in_transit", label)
        return STATUS_IN_TRANSIT
