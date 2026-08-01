"""Sample Helthjem API payloads shared by the test modules.

These mirror the shape of the ``getParcelTrackingDetails`` object Helthjem's
GraphQL endpoint returns, reconstructed from the live schema. They are **not**
captured from a real parcel yet — the status vocabulary in particular is
provisional (see ``parcels._STATUS_MAP``) — so treat the exact ``status`` and
``deliveryPoint.type`` values here as best-effort until a real payload confirms
them.

Kept in one module rather than inline per test: when the real shape turns out to
differ, there is then exactly one place to fix.
"""
from __future__ import annotations

from typing import Any

ACTIVE_CODE = "TESTHJEM00000001"
DELIVERED_CODE = "TESTHJEM00000002"


def event(
    status: str, created_at: str, description: str, location: str = "Oslo"
) -> dict[str, Any]:
    """One entry of Helthjem's own event timeline (``events[]``)."""
    return {
        "createdAt": created_at,
        "status": status,
        "location": location,
        "message": {"description": description},
    }


def delivered_sample(code: str = DELIVERED_CODE) -> dict[str, Any]:
    """A representative tracking response for a delivered parcel."""
    return {
        "trackingNumber": code,
        "status": "DELIVERED",
        "estimatedDelivery": {"date": "2026-04-29"},
        "servicePoint": None,
        "deliveryPoint": {"type": "HOME"},
        "events": [
            event("DELIVERED", "2026-04-29T13:12:42Z", "Pakken er levert"),
            event(
                "OUT_FOR_DELIVERY",
                "2026-04-29T08:46:00Z",
                "Pakken er ute for levering",
            ),
            event("IN_TRANSIT", "2026-04-28T15:52:17Z", "Ankommet terminal"),
            event("REGISTERED", "2026-04-27T23:03:58Z", "Sendingen er registrert"),
        ],
    }


def active_sample(code: str = ACTIVE_CODE) -> dict[str, Any]:
    """An out-for-delivery parcel with an estimated delivery date."""
    sample = delivered_sample(code)
    sample.update(
        {
            "status": "OUT_FOR_DELIVERY",
            "estimatedDelivery": {"date": "2026-04-29T13:00:00Z"},
            "events": sample["events"][1:],
        }
    )
    return sample


def pickup_sample(code: str = ACTIVE_CODE) -> dict[str, Any]:
    """A parcel waiting at a Helthjem service (pickup) point."""
    sample = active_sample(code)
    sample.update(
        {
            "status": "READY_FOR_PICKUP",
            "deliveryPoint": {"type": "SERVICE_POINT"},
            "servicePoint": {
                "name": "Helthjem Hentepunkt Grünerløkka",
                "address": "Thorvald Meyers gate 1, 0555 Oslo",
            },
        }
    )
    return sample


def graphql_response(parcel: dict[str, Any] | None) -> dict[str, Any]:
    """Wrap a parcel object in Helthjem's GraphQL response envelope."""
    return {"data": {"getParcelTrackingDetails": parcel}}
