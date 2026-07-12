"""Maps carriers to their provider class and required config keys."""

from __future__ import annotations

from typing import Any, Callable

import aiohttp

from ..const import (
    CARRIER_DHL,
    CARRIER_FEDEX,
    CARRIER_LAPOSTE,
    CARRIER_MONDIAL_RELAY,
    CARRIER_POSTNORD,
    CARRIER_UPS,
    CONF_API_KEY,
    CONF_DHL_API_KEY,
    CONF_FEDEX_CLIENT_ID,
    CONF_FEDEX_CLIENT_SECRET,
    CONF_MONDIAL_RELAY_LOGIN,
    CONF_MONDIAL_RELAY_PRIVATE_KEY,
    CONF_POSTNORD_API_KEY,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
)
from .base import TrackingProvider
from .dhl import DhlProvider
from .fedex import FedExProvider
from .laposte import LaPosteProvider
from .mondial_relay import MondialRelayProvider
from .postnord import PostNordProvider
from .ups import UpsProvider

# The config keys each carrier needs, in the order its provider's
# __init__ expects them (before the trailing aiohttp session argument).
CARRIER_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    CARRIER_LAPOSTE: (CONF_API_KEY,),
    CARRIER_FEDEX: (CONF_FEDEX_CLIENT_ID, CONF_FEDEX_CLIENT_SECRET),
    CARRIER_DHL: (CONF_DHL_API_KEY,),
    CARRIER_UPS: (CONF_UPS_CLIENT_ID, CONF_UPS_CLIENT_SECRET),
    CARRIER_MONDIAL_RELAY: (CONF_MONDIAL_RELAY_LOGIN, CONF_MONDIAL_RELAY_PRIVATE_KEY),
    CARRIER_POSTNORD: (CONF_POSTNORD_API_KEY,),
}

_PROVIDER_CLASSES: dict[str, Callable[..., TrackingProvider]] = {
    CARRIER_LAPOSTE: LaPosteProvider,
    CARRIER_FEDEX: FedExProvider,
    CARRIER_DHL: DhlProvider,
    CARRIER_UPS: UpsProvider,
    CARRIER_MONDIAL_RELAY: MondialRelayProvider,
    CARRIER_POSTNORD: PostNordProvider,
}


def is_carrier_configured(data: dict[str, Any], carrier: str) -> bool:
    """A carrier is enabled once all of its required keys are non-empty."""
    return all(data.get(key) for key in CARRIER_CONFIG_KEYS[carrier])


def configured_carriers(data: dict[str, Any]) -> list[str]:
    """Return every carrier for which credentials were provided."""
    return [carrier for carrier in CARRIER_CONFIG_KEYS if is_carrier_configured(data, carrier)]


def build_provider(
    carrier: str, data: dict[str, Any], session: aiohttp.ClientSession
) -> TrackingProvider:
    """Instantiate the provider for `carrier` from its configured keys."""
    values = (data[key] for key in CARRIER_CONFIG_KEYS[carrier])
    return _PROVIDER_CLASSES[carrier](*values, session)


def build_providers(
    data: dict[str, Any], session: aiohttp.ClientSession
) -> dict[str, TrackingProvider]:
    """Instantiate a provider for every carrier that has credentials configured."""
    return {
        carrier: build_provider(carrier, data, session)
        for carrier in configured_carriers(data)
    }
