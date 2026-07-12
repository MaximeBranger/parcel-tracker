"""Sensor entities for Parcel Tracker."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ALL_STATUSES,
    DOMAIN,
    STATUS_CREATED,
    STATUS_DELAYED,
    STATUS_DELIVERED,
)
from .coordinator import ParcelTrackerCoordinator
from .parcel import Parcel


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up parcel sensors from a config entry."""
    coordinator: ParcelTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
    device_info = _hub_device_info(entry)

    async_add_entities(
        [
            ParcelsActiveSensor(coordinator, entry, device_info),
            ParcelsDeliveredSensor(coordinator, entry, device_info),
            ParcelsWaitingSensor(coordinator, entry, device_info),
            ParcelsTodaySensor(coordinator, entry, device_info),
            ParcelsLateSensor(coordinator, entry, device_info),
        ]
    )

    entities: dict[str, ParcelSensor] = {}

    def _create(parcel_id: str) -> ParcelSensor:
        sensor = ParcelSensor(coordinator, parcel_id, device_info)
        entities[parcel_id] = sensor
        return sensor

    async_add_entities(
        _create(parcel_id)
        for parcel_id, parcel in coordinator.data.items()
        if not parcel.archived
    )

    @callback
    def _async_add_parcel(parcel_id: str) -> None:
        if parcel_id in entities:
            return
        async_add_entities([_create(parcel_id)])

    async def _async_remove_parcel(parcel_id: str) -> None:
        sensor = entities.pop(parcel_id, None)
        if sensor is not None:
            await sensor.async_remove()

    entry.async_on_unload(
        async_dispatcher_connect(hass, coordinator.signal_added, _async_add_parcel)
    )
    entry.async_on_unload(
        async_dispatcher_connect(hass, coordinator.signal_removed, _async_remove_parcel)
    )


def _hub_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Group all Parcel Tracker entities under a single hub device."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Parcel Tracker",
        manufacturer="Parcel Tracker",
        entry_type=DeviceEntryType.SERVICE,
    )


class ParcelSensor(CoordinatorEntity[ParcelTrackerCoordinator], SensorEntity):
    """Representation of a single tracked parcel."""

    _attr_translation_key = "parcel"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ALL_STATUSES

    def __init__(
        self,
        coordinator: ParcelTrackerCoordinator,
        parcel_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._parcel_id = parcel_id
        self._attr_unique_id = parcel_id
        self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        return super().available and self._parcel_id in self.coordinator.data

    @property
    def name(self) -> str | None:
        """Reflect the parcel's current display name, editable after creation."""
        parcel = self.coordinator.data.get(self._parcel_id)
        return parcel.display_name if parcel else None

    @property
    def native_value(self) -> str | None:
        parcel = self.coordinator.data.get(self._parcel_id)
        return parcel.status if parcel else None

    @property
    def extra_state_attributes(self) -> dict:
        parcel = self.coordinator.data[self._parcel_id]
        return {
            "tracking_number": parcel.tracking_number,
            "carrier": parcel.carrier,
            "notes": parcel.notes,
            "history": parcel.history,
            "estimated_delivery": parcel.estimated_delivery,
            "last_location": parcel.last_location,
            "last_update": parcel.last_update,
            "tracking_url": parcel.tracking_url,
            "days_since_shipping": self._days_since_shipping(parcel),
        }

    @staticmethod
    def _days_since_shipping(parcel: Parcel) -> int | None:
        if not parcel.created_at:
            return None
        try:
            created = datetime.fromisoformat(parcel.created_at)
        except ValueError:
            return None
        now = datetime.now(created.tzinfo or timezone.utc)
        return (now - created).days


class ParcelsGlobalSensor(CoordinatorEntity[ParcelTrackerCoordinator], SensorEntity):
    """Base class for the global parcel counter sensors."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "parcels"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: ParcelTrackerCoordinator,
        entry: ConfigEntry,
        translation_key: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry.entry_id}_{translation_key}"
        self._attr_device_info = device_info

    @property
    def _non_archived_parcels(self) -> list[Parcel]:
        """Global counters only ever consider non-archived parcels."""
        return [parcel for parcel in self.coordinator.data.values() if not parcel.archived]


class ParcelsActiveSensor(ParcelsGlobalSensor):
    """Count of non-archived parcels not yet delivered."""

    def __init__(self, coordinator, entry, device_info):
        super().__init__(coordinator, entry, "parcels_active", device_info)

    @property
    def native_value(self) -> int:
        return sum(1 for p in self._non_archived_parcels if p.status != STATUS_DELIVERED)


class ParcelsDeliveredSensor(ParcelsGlobalSensor):
    """Count of delivered, not-yet-archived parcels."""

    def __init__(self, coordinator, entry, device_info):
        super().__init__(coordinator, entry, "parcels_delivered", device_info)

    @property
    def native_value(self) -> int:
        return sum(1 for p in self._non_archived_parcels if p.status == STATUS_DELIVERED)


class ParcelsWaitingSensor(ParcelsGlobalSensor):
    """Count of parcels not yet taken in charge by the carrier."""

    def __init__(self, coordinator, entry, device_info):
        super().__init__(coordinator, entry, "parcels_waiting", device_info)

    @property
    def native_value(self) -> int:
        return sum(1 for p in self._non_archived_parcels if p.status == STATUS_CREATED)


class ParcelsTodaySensor(ParcelsGlobalSensor):
    """Count of parcels delivered today."""

    def __init__(self, coordinator, entry, device_info):
        super().__init__(coordinator, entry, "parcels_today", device_info)

    @property
    def native_value(self) -> int:
        today = dt_util.utcnow().date()
        count = 0
        for parcel in self._non_archived_parcels:
            if parcel.status != STATUS_DELIVERED or not parcel.last_update:
                continue
            updated = dt_util.parse_datetime(parcel.last_update)
            if updated and dt_util.as_utc(updated).date() == today:
                count += 1
        return count


class ParcelsLateSensor(ParcelsGlobalSensor):
    """Count of delayed parcels."""

    def __init__(self, coordinator, entry, device_info):
        super().__init__(coordinator, entry, "parcels_late", device_info)

    @property
    def native_value(self) -> int:
        return sum(1 for p in self._non_archived_parcels if p.status == STATUS_DELAYED)
