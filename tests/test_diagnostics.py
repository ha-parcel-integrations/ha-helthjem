"""Tests for Helthjem diagnostics."""
from unittest.mock import MagicMock

from custom_components.helthjem.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {"parcels": [{"tracking_code": "TESTHJEM00000001"}]}
    entry.runtime_data.coordinator.data = [
        {
            "barcode": "TESTHJEM00000001",
            "sender": None,
            "receiver": None,
            "status": "out_for_delivery",
            "pickup_point": "Helthjem Hentepunkt Grünerløkka",
            "raw": {
                "trackingNumber": "TESTHJEM00000001",
                "servicePoint": {"name": "Hentepunkt", "address": "Meyers gate 1"},
                "sender": {"postalCode": "0555"},
                "events": [{"location": "Oslo"}],
            },
        }
    ]
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {"incoming_active": 1, "delivered": 0}
    # tracking codes and payload PII are redacted, at every nesting level
    assert result["entry_options"]["parcels"][0]["tracking_code"] == "**REDACTED**"
    assert result["incoming"][0]["barcode"] == "**REDACTED**"
    assert result["incoming"][0]["pickup_point"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["servicePoint"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["sender"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["events"][0]["location"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "out_for_delivery"
