"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

The two carrier-specific parts are :data:`_STATUS_MAP` and
:func:`normalize_parcel` (plus :func:`build_history`'s field lookups).
Everything else — the timestamp parsing, the sort contract, the delivered
filter, the one-shot warnings for unmapped statuses and unconfirmed fields — is
suite-wide machinery and should be left alone.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-helthjem/issues/new"
    "?template=unrecognised_status.yml"
)

# Helthjem's ``EventStatusType`` enum, mapped onto the canonical ParcelStatus.
# The parcel-level ``status`` and each event's ``status`` share this one enum,
# so a single map serves both.
#
# **Provisional — unverified until a real Helthjem parcel confirms it.** The
# enum's members cannot be listed (GraphQL introspection is disabled on the
# endpoint), so these keys are a best-effort reconstruction. Any value not below
# surfaces as ``unknown`` plus a one-shot warning with an issue link — that is
# how the map grows once real values arrive. Prefer mapping too little over
# mapping wrongly.
_STATUS_MAP: dict[str, ParcelStatus] = {
    "REGISTERED": ParcelStatus.REGISTERED,
    "PRE_TRANSIT": ParcelStatus.REGISTERED,
    "BOOKED": ParcelStatus.REGISTERED,
    "IN_TRANSIT": ParcelStatus.IN_TRANSIT,
    "COLLECTED": ParcelStatus.IN_TRANSIT,
    "AT_TERMINAL": ParcelStatus.IN_TRANSIT,
    "OUT_FOR_DELIVERY": ParcelStatus.OUT_FOR_DELIVERY,
    "READY_FOR_PICKUP": ParcelStatus.AT_PICKUP_POINT,
    "DELIVERED": ParcelStatus.DELIVERED,
    "RETURNED": ParcelStatus.RETURNING,
    "DEVIATION": ParcelStatus.PROBLEM,
}

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Helthjem status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


# Pre-release data collection. This integration was reconstructed from
# Helthjem's live GraphQL schema without ever seeing a real parcel payload, so
# a few things are still unconfirmed and can only be filled in from real data:
#
#  * ``EventStatusType`` — the full status vocabulary (``_warn_unmapped_status``
#    above already reports any value missing from ``_STATUS_MAP``);
#  * ``DeliveryPointType`` — the delivery-point kind, which may be a cleaner
#    pickup signal than the status alone;
#  * the ``estimatedDelivery.date`` format, and whether the response's
#    ``trackingNumber`` matches the reference the user entered.
#
# Each distinct observed value is logged **once** at WARNING with the issue
# link, so a user with a real Helthjem parcel can report it and grow the maps.
# Remove these once the mapping is confirmed against real payloads.
_observed_values_logged: set[tuple[str, str]] = set()


def _warn_observed_value(field: str, value: object) -> None:
    """Log a distinct observed value for a still-unconfirmed field, once."""
    if value in (None, ""):
        return
    key = (field, str(value))
    if key in _observed_values_logged:
        return
    _observed_values_logged.add(key)
    _LOGGER.warning(
        "Helthjem %s=%r observed — this field is not confirmed yet. Please "
        "help us verify the mapping by opening an issue and pasting this line "
        "(and, ideally, your redacted diagnostics): %s",
        field,
        value,
        NEW_ISSUE_URL,
    )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a carrier status code to a canonical :class:`ParcelStatus`.

    ``None`` (a not-yet-scanned parcel) reports ``unknown`` silently; an
    unrecognised code reports ``unknown`` with a one-shot warning.
    """
    if not code:
        return ParcelStatus.UNKNOWN
    mapped = _STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return ParcelStatus.UNKNOWN


def map_event_status(code: str | None) -> ParcelStatus | None:
    """Map a history entry's status code to a canonical status, or ``None``.

    Unmapped codes keep ``status: null`` on the history entry (rather than
    ``unknown``, so a consumer can tell "no mapping" from "mapped to unknown")
    and warn once, reusing the parcel-status one-shot set.
    """
    if not code:
        return None
    mapped = _STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return None


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. Adjust the numeric branch if
    your carrier stamps in seconds.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def format_dimensions(
    length: float | None, width: float | None, height: float | None
) -> dict[str, Any] | None:
    """Return the canonical ``dimensions`` dict, or ``None`` when incomplete.

    Units contract: **centimetres**, with ``text`` pre-formatted as
    ``"L x W x H cm"`` (integer values, lowercase ``x``) so dashboards can show
    a dimension without doing their own formatting. Convert before calling if
    the carrier reports millimetres or inches.
    """
    if length is None or width is None or height is None:
        return None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{int(length)} x {int(width)} x {int(height)} cm",
    }


def build_history(
    events: list | None, *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from the carrier's event list.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. ``raw_status`` is the carrier's own text, or
    its event code when the API has no human-readable text. Sorted oldest →
    newest and capped to the most recent ``max_events``.

    A Helthjem event is ``{createdAt, status, location, message: {description}}``.
    ``status`` is the same ``EventStatusType`` enum as the parcel-level status,
    and ``message.description`` is Helthjem's own human text for the event.
    """
    parseable: list[tuple[datetime, dict]] = []
    unparseable: list[dict] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        timestamp = to_iso_timestamp(event.get("createdAt"))
        if not timestamp:
            continue
        message = event.get("message") or {}
        entry = {
            "timestamp": timestamp,
            "status": map_event_status(event.get("status")),
            "raw_status": message.get("description") or event.get("status"),
        }
        parsed = parse_iso(timestamp)
        if parsed is None:
            unparseable.append(entry)
        else:
            parseable.append((parsed, entry))
    parseable.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in parseable] + unparseable
    return ordered[-max_events:]


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


def _delivered_at(events: list | None) -> str | None:
    """Return the ISO timestamp of the delivery event, if any.

    Helthjem exposes no top-level delivered timestamp, so the delivery time is
    the ``createdAt`` of the newest event whose status maps to ``DELIVERED``.
    """
    latest: datetime | None = None
    latest_iso: str | None = None
    for event in events or []:
        if not isinstance(event, dict):
            continue
        if map_event_status(event.get("status")) is not ParcelStatus.DELIVERED:
            continue
        timestamp = to_iso_timestamp(event.get("createdAt"))
        parsed = parse_iso(timestamp)
        if parsed is not None and (latest is None or parsed > latest):
            latest, latest_iso = parsed, timestamp
    return latest_iso


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are the contract**: every carrier in the
    suite returns exactly these, in this order, and the aggregator and
    cross-carrier dashboards depend on it. A key is ``None`` when Helthjem does
    not expose it (sender, receiver, weight, dimensions) — never omitted.

    Rules the body honours:

    * ``status`` is canonical, ``raw_status`` is the carrier's own text.
    * A delivered parcel has ``delivered_at`` set and ``planned_from`` /
      ``planned_to`` cleared — the ETA is meaningless once it has arrived.
    * ``planned_to`` is ``None`` for a point estimate; only fill it when the
      carrier genuinely reports a *window*.
    * ``weight`` is kilograms, ``dimensions`` centimetres (see
      :func:`format_dimensions`).
    * ``history`` is ``None`` when the option is off — the key still exists.
    """
    tracking_code = raw.get("trackingNumber")
    status_code = raw.get("status")
    status = map_parcel_status(status_code)
    delivered = status is ParcelStatus.DELIVERED

    # Helthjem reports a single estimated-delivery *date*, not a window, so
    # ``planned_to`` stays ``None`` (a point estimate).
    eta = raw.get("estimatedDelivery") or {}
    planned_from = to_iso_timestamp(eta.get("date"))

    # No top-level delivered timestamp — take it from the delivered event.
    delivered_at = _delivered_at(raw.get("events")) if delivered else None

    service_point = raw.get("servicePoint") or {}

    # Pre-release: surface the still-unconfirmed DeliveryPointType so a real
    # parcel tells us its vocabulary (see _warn_observed_value).
    delivery_point = raw.get("deliveryPoint") or {}
    _warn_observed_value("deliveryPoint.type", delivery_point.get("type"))

    return {
        "carrier": "Helthjem",
        "barcode": tracking_code,
        # Helthjem's tracking type exposes neither sender nor receiver name.
        "sender": None,
        "receiver": None,
        "status": status,
        "raw_status": status_code,
        "delivered": delivered,
        "delivered_at": delivered_at,
        "planned_from": None if delivered else planned_from,
        "planned_to": None,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": service_point.get("name") or None,
        "url": tracking_url(tracking_code),
        # Weight and dimensions are not exposed by this tracking type.
        "weight": None,
        "dimensions": None,
        "history": build_history(raw.get("events")) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(
        CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
    )
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
