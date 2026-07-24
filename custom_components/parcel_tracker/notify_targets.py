"""Shared listing of possible per-parcel notify targets.

Home Assistant moved from one service per target (e.g.
`notify.mobile_app_phone`) to entities called through `notify.send_message`,
but many notify integrations (and older installs) still only expose their
targets the old way, so both are offered here. `send_message` itself is
excluded from the service list since it's the generic dispatcher, not a
target. Used both by the options flow (config_flow.py) and by the
`get_notify_targets` service (services.py), which lets the parcel_tracker-card
frontend populate the same picker without access to the entity registry.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def list_notify_targets(hass: HomeAssistant) -> list[str]:
    """Return every usable notify target: notify.* entities, then legacy services."""
    registry = er.async_get(hass)
    entity_ids = sorted(
        entry.entity_id for entry in registry.entities.values() if entry.domain == "notify"
    )
    services = sorted(hass.services.async_services().get("notify", {}).keys() - {"send_message"})
    return [*entity_ids, *services]
