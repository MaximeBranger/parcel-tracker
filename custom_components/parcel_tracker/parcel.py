"""Data model for a tracked parcel."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import uuid

from .const import CARRIER_LAPOSTE, STATUS_CREATED


@dataclass
class Parcel:
    """A single tracked parcel."""

    tracking_number: str
    carrier: str = CARRIER_LAPOSTE
    name: str = ""
    notes: str = ""
    notify_target: str = ""
    status: str = STATUS_CREATED
    history: list[dict] = field(default_factory=list)
    estimated_delivery: str | None = None
    last_location: str | None = None
    last_update: str | None = None
    tracking_url: str | None = None
    last_error: str | None = None
    archived: bool = False
    created_at: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def display_name(self) -> str:
        """Return the user-facing name of the parcel."""
        return self.name or self.tracking_number

    def to_dict(self) -> dict:
        """Serialize the parcel for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Parcel":
        """Build a parcel from stored data, ignoring unknown/legacy keys."""
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})
