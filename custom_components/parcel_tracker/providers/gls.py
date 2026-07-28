"""API client for GLS's public, unofficial parcel tracking endpoint.

Unlike DPD and Mondial Relay, GLS's *official* tracking API (MyGLS) is also
professional-contract-only and undocumented outside that contract. This
provider instead calls the `rstt001` endpoint that GLS's own public tracking
website uses (`https://api.gls-group.eu/app/service/open/rest/{country}/en/
rstt001?match={tracking_number}`), which needs no credentials at all — only
a country group code (e.g. `FR`, `DE`) selected at setup time, since that
code is part of the URL path. It is not published as a stable, supported API
by GLS: there is no SLA, no changelog and no guarantee it keeps working, so
treat the field mapping below as a best-effort starting point to confirm
against real tracking numbers, not a verified contract.
"""

from __future__ import annotations

import logging
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
    STATUS_RETURNED_TO_SENDER,
    STATUS_TAKEN_IN_CHARGE,
)
from .base import (
    ParcelTrackerApiError,
    ParcelTrackerNotFoundError,
    TrackingProvider,
)

_LOGGER = logging.getLogger(__name__)

API_URL = "https://api.gls-group.eu/app/service/open/rest/{country}/en/rstt001"
PUBLIC_TRACKING_URL = (
    "https://gls-group.eu/{country}/en/parcel-tracking?match={tracking_number}"
)

LABEL_STATUS_MAP: dict[str, str] = {
    "pris en charge": STATUS_TAKEN_IN_CHARGE,
    "enlevé": STATUS_TAKEN_IN_CHARGE,
    "collected": STATUS_TAKEN_IN_CHARGE,
    "en cours de transport": STATUS_IN_TRANSIT,
    "en transit": STATUS_IN_TRANSIT,
    "in transit": STATUS_IN_TRANSIT,
    "arrivé": STATUS_AT_SORTING_CENTER,
    "arrived at the parcelshop": STATUS_AT_SORTING_CENTER,
    "en cours de livraison": STATUS_OUT_FOR_DELIVERY,
    "out for delivery": STATUS_OUT_FOR_DELIVERY,
    "livré": STATUS_DELIVERED,
    "delivered": STATUS_DELIVERED,
    "anomalie": STATUS_INCIDENT,
    "incident": STATUS_INCIDENT,
    "retour": STATUS_RETURNED_TO_SENDER,
    "returned": STATUS_RETURNED_TO_SENDER,
}


class GlsProvider(TrackingProvider):
    """Client for GLS's public (unofficial) `rstt001` tracking endpoint."""

    carrier = CARRIER_GLS

    def __init__(self, country: str, session: aiohttp.ClientSession) -> None:
        self._country = country.upper()
        self._session = session

    async def async_validate_credentials(self) -> None:
        """Raise if the configured country code isn't accepted by the endpoint.

        There are no real credentials to check here, only the country group
        code baked into the URL, so this just confirms the endpoint responds
        for that country using a made-up tracking number.
        """
        try:
            await self.async_track("00000000000")
        except ParcelTrackerNotFoundError:
            return

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        async with self._session.get(
            API_URL.format(country=self._country),
            params={"match": tracking_number},
        ) as response:
            if response.status != 200:
                raise ParcelTrackerApiError(f"GLS API returned HTTP {response.status}")
            payload = await response.json(content_type=None)

        shipments = payload.get("tuStatus") or []
        if not shipments:
            raise ParcelTrackerNotFoundError(f"Unknown tracking number: {tracking_number}")

        return self._normalize(tracking_number, shipments[0])

    def _normalize(self, tracking_number: str, shipment: dict[str, Any]) -> dict[str, Any]:
        """Turn a raw `tuStatus[0]` object into our internal parcel fields."""
        history = sorted(
            (
                {
                    "date": self._combine_date_time(event.get("date"), event.get("time")),
                    "label": event.get("evtDscr"),
                    "location": event.get("location"),
                }
                for event in shipment.get("history") or []
                if event.get("date")
            ),
            key=lambda item: item["date"] or "",
        )
        last_event = history[-1] if history else None

        return {
            "status": self._status_from_history(last_event),
            "history": history,
            "estimated_delivery": shipment.get("estDlvrDate"),
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else None,
            "tracking_url": PUBLIC_TRACKING_URL.format(
                country=self._country.lower(), tracking_number=tracking_number
            ),
        }

    @staticmethod
    def _combine_date_time(date: str | None, time_: str | None) -> str | None:
        if not date:
            return None
        return f"{date} {time_}" if time_ else date

    @classmethod
    def _status_from_history(cls, last_event: dict[str, Any] | None) -> str:
        if not last_event:
            return STATUS_CREATED

        label = (last_event.get("label") or "").strip().lower()
        for known_label, status in LABEL_STATUS_MAP.items():
            if known_label in label:
                return status

        _LOGGER.debug("Unrecognized GLS label %r, defaulting to in_transit", label)
        return STATUS_IN_TRANSIT
