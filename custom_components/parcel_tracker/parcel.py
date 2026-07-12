"""Data model for a tracked parcel."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid


@dataclass
class Parcel:
    """A single tracked parcel."""

    tracking_number: str
    carrier: str = "laposte"
    name: str = ""
    notes: str = ""
    status: str = "created"
    history: list[dict] = field(default_factory=list)
    archived: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
