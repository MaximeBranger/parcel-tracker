"""Sensor entities for Parcel Tracker."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ParcelTrackerCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up parcel sensors from a config entry."""
    coordinator: ParcelTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ParcelSensor(coordinator, parcel_id)
        for parcel_id, parcel in coordinator.data.items()
        if not parcel.archived
    )


class ParcelSensor(CoordinatorEntity[ParcelTrackerCoordinator], SensorEntity):
    """Representation of a single tracked parcel."""

    def __init__(self, coordinator: ParcelTrackerCoordinator, parcel_id: str) -> None:
        super().__init__(coordinator)
        self._parcel_id = parcel_id
        self._attr_unique_id = parcel_id

    @property
    def native_value(self) -> str:
        return self.coordinator.data[self._parcel_id].status

    @property
    def extra_state_attributes(self) -> dict:
        parcel = self.coordinator.data[self._parcel_id]
        return {
            "tracking_number": parcel.tracking_number,
            "carrier": parcel.carrier,
            "history": parcel.history,
        }
