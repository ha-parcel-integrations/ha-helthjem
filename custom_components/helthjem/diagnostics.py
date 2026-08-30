"""Diagnostics support for the Helthjem parcel tracker integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HelthjemConfigEntry

# Diagnostics are pasted into public issues, so redact anything that
# identifies a person, an address or a specific parcel. Over-redacting is
# cheap; under-redacting leaks a user's home address into a GitHub thread.
#
# Diagnostics are pasted into public issues, so redact anything that could
# identify a person, an address or a specific parcel.
TO_REDACT = {
    # canonical fields we publish ourselves
    "tracking_code",
    "barcode",
    "sender",
    "receiver",
    "url",
    "pickup_point",
    # Helthjem GraphQL payload fields
    "trackingNumber",
    "servicePoint",  # pickup point name + address
    "address",
    "postalCode",  # sender.postalCode
    "location",  # per-event place name
    "name",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HelthjemConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Helthjem config entry."""
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "polling": {
            "current_tier_minutes": coordinator.current_tier_minutes,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
        },
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
        },
        "incoming": async_redact_data(coordinator.data or [], TO_REDACT),
        "delivered": async_redact_data(coordinator.delivered or [], TO_REDACT),
    }
