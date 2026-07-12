"""Constants for the Parcel Tracker integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "parcel_tracker"
PLATFORMS = ["sensor"]

CONF_API_KEY = "api_key"
CONF_FEDEX_CLIENT_ID = "fedex_client_id"
CONF_FEDEX_CLIENT_SECRET = "fedex_client_secret"
CONF_DHL_API_KEY = "dhl_api_key"
CONF_UPS_CLIENT_ID = "ups_client_id"
CONF_UPS_CLIENT_SECRET = "ups_client_secret"
CONF_MONDIAL_RELAY_LOGIN = "mondial_relay_login"
CONF_MONDIAL_RELAY_PRIVATE_KEY = "mondial_relay_private_key"

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=15)

# Carriers. Each maps to a provider in providers/registry.py, which also
# defines which of the CONF_* keys above are required to enable it.
CARRIER_LAPOSTE = "laposte"
CARRIER_FEDEX = "fedex"
CARRIER_DHL = "dhl"
CARRIER_UPS = "ups"
CARRIER_MONDIAL_RELAY = "mondial_relay"

ALL_CARRIERS = [
    CARRIER_LAPOSTE,
    CARRIER_FEDEX,
    CARRIER_DHL,
    CARRIER_UPS,
    CARRIER_MONDIAL_RELAY,
]

CARRIER_LABELS: dict[str, str] = {
    CARRIER_LAPOSTE: "La Poste",
    CARRIER_FEDEX: "FedEx",
    CARRIER_DHL: "DHL",
    CARRIER_UPS: "UPS",
    CARRIER_MONDIAL_RELAY: "Mondial Relay",
}

# Parcel statuses, as listed in SPECIFICATIONS.md.
STATUS_CREATED = "created"
STATUS_TAKEN_IN_CHARGE = "taken_in_charge"
STATUS_IN_TRANSIT = "in_transit"
STATUS_AT_SORTING_CENTER = "at_sorting_center"
STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
STATUS_DELIVERED = "delivered"
STATUS_DELAYED = "delayed"
STATUS_INCIDENT = "incident"
STATUS_RETURNED_TO_SENDER = "returned_to_sender"

ALL_STATUSES = [
    STATUS_CREATED,
    STATUS_TAKEN_IN_CHARGE,
    STATUS_IN_TRANSIT,
    STATUS_AT_SORTING_CENTER,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_DELIVERED,
    STATUS_DELAYED,
    STATUS_INCIDENT,
    STATUS_RETURNED_TO_SENDER,
]

# Home Assistant events, as listed in SPECIFICATIONS.md.
EVENT_PARCEL_ADDED = "parcel_added"
EVENT_PARCEL_UPDATED = "parcel_updated"
EVENT_PARCEL_DELIVERED = "parcel_delivered"
EVENT_PARCEL_REMOVED = "parcel_removed"
EVENT_PARCEL_ERROR = "parcel_error"

# Dispatcher signals used to add/remove parcel entities without a config
# entry reload (parcels are managed dynamically via services, not via flows).
SIGNAL_PARCEL_ADDED = f"{DOMAIN}_parcel_added_{{entry_id}}"
SIGNAL_PARCEL_REMOVED = f"{DOMAIN}_parcel_removed_{{entry_id}}"
