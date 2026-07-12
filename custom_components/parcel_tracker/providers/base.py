"""Shared interface and errors for tracking providers.

Every carrier client normalizes its response to the same dict shape so the
coordinator can treat all providers identically:

    {
        "status": <one of const.ALL_STATUSES>,
        "history": [{"date": ..., "label": ..., "location": ...}, ...],
        "estimated_delivery": str | None,
        "last_location": str | None,
        "last_update": str | None,
        "tracking_url": str | None,
    }
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ParcelTrackerApiError(Exception):
    """Base error for tracking provider clients."""


class ParcelTrackerAuthError(ParcelTrackerApiError):
    """Raised when a provider rejects the configured credentials."""


class ParcelTrackerNotFoundError(ParcelTrackerApiError):
    """Raised when the tracking number is unknown to the provider."""


class TrackingProvider(ABC):
    """Base class for a single carrier's tracking client."""

    carrier: str

    @abstractmethod
    async def async_validate_credentials(self) -> None:
        """Raise ParcelTrackerAuthError if the configured credentials are rejected."""

    @abstractmethod
    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
