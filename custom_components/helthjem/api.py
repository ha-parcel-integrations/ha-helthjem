"""Helthjem public tracking API client.

Helthjem exposes the same **keyless GraphQL** backend its consumer tracking page
(https://helthjem.no/sporing/) uses. There is no authentication — the parcel
reference alone is the input. The client keeps the contract the coordinator
relies on:

* ``async_get_parcel`` returns the raw ``getParcelTrackingDetails`` dict on
  success,
* returns ``None`` when the reference is unknown or not yet scanned (the server
  answers HTTP 200 with ``data.getParcelTrackingDetails == null`` and no
  ``errors`` — a normal, expected state, never an error),
* raises :class:`HelthjemApiError` for anything else (a GraphQL ``errors``
  array, a non-200 status, or an unparseable body),
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    TRACKING_API_URL,
    TRACKING_ORIGIN,
    TRACKING_QUERY,
    TRACKING_REFERER,
)

_LOGGER = logging.getLogger(__name__)


class HelthjemApiError(Exception):
    """Raised when a Helthjem API call returns an unexpected response."""

    def __init__(self, detail: str) -> None:
        """Store the detail that triggered the error."""
        super().__init__(f"Helthjem API request failed: {detail}")
        self.detail = detail


class HelthjemApiClient:
    """Client for the public Helthjem GraphQL tracking endpoint."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details by reference.

        Returns the ``getParcelTrackingDetails`` dict for a known parcel, or
        ``None`` when Helthjem reports the reference as unknown — which is also
        what a not-yet-scanned parcel gets. Any GraphQL error, non-200 status or
        unparseable body raises :class:`HelthjemApiError`; network errors
        propagate as ``aiohttp.ClientError``.
        """
        payload = {"query": TRACKING_QUERY, "variables": {"ref": tracking_code}}
        headers = {
            "Content-Type": "application/json",
            "Origin": TRACKING_ORIGIN,
            "Referer": TRACKING_REFERER,
        }
        async with self._session.post(
            TRACKING_API_URL, json=payload, headers=headers
        ) as response:
            if response.status != 200:
                raise HelthjemApiError(f"HTTP {response.status}")
            try:
                body = await response.json(content_type=None)
            except ValueError as err:
                raise HelthjemApiError(f"unparseable body ({err})") from err

        if not isinstance(body, dict):
            raise HelthjemApiError("unexpected body (not a JSON object)")

        # A GraphQL error (schema drift, a server-side failure) is not a
        # "not found" — surface it so the coordinator can fall back to cache.
        if body.get("errors"):
            raise HelthjemApiError(str(body["errors"]))

        data = body.get("data")
        if not isinstance(data, dict):
            raise HelthjemApiError("response carried no data object")

        parcel = data.get("getParcelTrackingDetails")
        if parcel is None:
            # Unknown or not-yet-scanned reference — an expected state.
            return None
        if not isinstance(parcel, dict):
            _LOGGER.warning(
                "Helthjem returned a non-object parcel for %s", tracking_code
            )
            return None
        return parcel
