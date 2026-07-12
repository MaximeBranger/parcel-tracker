"""API client for the Mondial Relay WSI2 tracing webservice.

Unlike the other providers, WSI2 is an older SOAP/XML webservice rather than
a documented public REST API: there is no self-service sandbox, and its
request-signing scheme (concatenation order fed into the MD5 `Security`
hash) is only described in the merchant WSI2 PDF handed out with a Mondial
Relay professional account, not in a public spec. `_security_hash` below
follows the commonly-documented order (Enseigne + Expedition + Langue +
private key) used by existing WSI2 integrations, but — like the La Poste
timeline labels — treat it as a best-effort starting point to confirm
against real credentials, not a verified contract.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from xml.etree import ElementTree

import aiohttp

from ..const import (
    CARRIER_MONDIAL_RELAY,
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

API_URL = "https://api.mondialrelay.com/Web_Services.asmx"
SOAP_ACTION = "http://www.mondialrelay.fr/webservice/WSI2_TracingColisDetaille"
XML_NAMESPACE = "http://www.mondialrelay.fr/webservice/"
PUBLIC_TRACKING_URL = (
    "https://www.mondialrelay.fr/suivi-de-colis?numeroExpedition={tracking_number}"
)

# Error codes documented as "unknown shipment number" by WSI2.
NOT_FOUND_ERROR_CODES = {"73", "84"}

LABEL_STATUS_MAP: dict[str, str] = {
    "pris en charge": STATUS_TAKEN_IN_CHARGE,
    "enlèvement": STATUS_TAKEN_IN_CHARGE,
    "expédition prise en compte": STATUS_CREATED,
    "colis en cours d'acheminement": STATUS_IN_TRANSIT,
    "en cours d'acheminement": STATUS_IN_TRANSIT,
    "arrivée à l'agence": STATUS_AT_SORTING_CENTER,
    "arrivé en agence": STATUS_AT_SORTING_CENTER,
    "colis en cours de livraison": STATUS_OUT_FOR_DELIVERY,
    "en livraison": STATUS_OUT_FOR_DELIVERY,
    "disponible en point relais": STATUS_OUT_FOR_DELIVERY,
    "livré": STATUS_DELIVERED,
    "distribué": STATUS_DELIVERED,
    "anomalie": STATUS_INCIDENT,
    "litige": STATUS_INCIDENT,
    "retour expéditeur": STATUS_RETURNED_TO_SENDER,
    "retourné": STATUS_RETURNED_TO_SENDER,
}


class MondialRelayProvider(TrackingProvider):
    """Client for Mondial Relay's WSI2 `Tracing_Colis_Detaille` webservice."""

    carrier = CARRIER_MONDIAL_RELAY

    def __init__(self, login: str, private_key: str, session: aiohttp.ClientSession) -> None:
        self._login = login
        self._private_key = private_key
        self._session = session

    async def async_validate_credentials(self) -> None:
        """Raise if the configured login/private key are rejected.

        WSI2 has no dedicated key-check operation, so this tracks a
        made-up number: any response other than an authentication error
        (bad Security hash / unknown Enseigne) is treated as valid.
        """
        try:
            await self.async_track("00000000000000")
        except ParcelTrackerNotFoundError:
            return

    async def async_track(self, tracking_number: str) -> dict[str, Any]:
        """Fetch and normalize the tracking status for a single parcel."""
        envelope = self._build_envelope(tracking_number)
        async with self._session.post(
            API_URL,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": SOAP_ACTION,
            },
            data=envelope,
        ) as response:
            if response.status != 200:
                raise ParcelTrackerApiError(
                    f"Mondial Relay API returned HTTP {response.status}"
                )
            body = await response.text()

        return self._parse_response(tracking_number, body)

    def _build_envelope(self, tracking_number: str) -> str:
        security = self._security_hash(tracking_number, "fr")
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            "<soap:Body>"
            f'<WSI2_TracingColisDetaille xmlns="{XML_NAMESPACE}">'
            f"<Enseigne>{self._login}</Enseigne>"
            f"<Expedition>{tracking_number}</Expedition>"
            "<Langue>fr</Langue>"
            f"<Security>{security}</Security>"
            "</WSI2_TracingColisDetaille>"
            "</soap:Body>"
            "</soap:Envelope>"
        )

    def _security_hash(self, tracking_number: str, langue: str) -> str:
        raw = f"{self._login}{tracking_number}{langue}{self._private_key}"
        return hashlib.md5(raw.encode()).hexdigest().upper()  # noqa: S324 (WSI2-mandated scheme)

    def _parse_response(self, tracking_number: str, body: str) -> dict[str, Any]:
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as err:
            raise ParcelTrackerApiError("Malformed Mondial Relay XML response") from err

        ns = {"ns": XML_NAMESPACE}
        result = root.find(".//ns:WSI2_TracingColisDetailleResult", ns)
        if result is None:
            raise ParcelTrackerApiError("Unexpected Mondial Relay XML response")

        error_code = (result.findtext("ns:Erreur", default="0", namespaces=ns) or "0").strip()
        if error_code in NOT_FOUND_ERROR_CODES:
            raise ParcelTrackerNotFoundError(f"Unknown tracking number: {tracking_number}")
        if error_code not in ("0", ""):
            raise ParcelTrackerAuthError(
                f"Mondial Relay rejected the request (error {error_code}); "
                "check login/private key"
            )

        history = sorted(
            (
                {
                    "date": self._combine_date_time(
                        detail.findtext("ns:Date", namespaces=ns),
                        detail.findtext("ns:Heure", namespaces=ns),
                    ),
                    "label": detail.findtext("ns:Libelle", namespaces=ns),
                    "location": detail.findtext("ns:Ville", namespaces=ns),
                }
                for detail in result.findall(".//ns:Tracing_Details", ns)
                if detail.findtext("ns:Date", namespaces=ns)
            ),
            key=lambda item: item["date"] or "",
        )
        last_event = history[-1] if history else None

        return {
            "status": self._status_from_history(last_event),
            "history": history,
            "estimated_delivery": None,
            "last_location": last_event["location"] if last_event else None,
            "last_update": last_event["date"] if last_event else None,
            "tracking_url": PUBLIC_TRACKING_URL.format(tracking_number=tracking_number),
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

        _LOGGER.debug(
            "Unrecognized Mondial Relay label %r, defaulting to in_transit", label
        )
        return STATUS_IN_TRANSIT
