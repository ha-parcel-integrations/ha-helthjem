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

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
import logging
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONFIRMED_DELIVERY_POINT_TYPES,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

_ZONE = ZoneInfo("Europe/Oslo")

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
    "DELIVERING": ParcelStatus.OUT_FOR_DELIVERY,
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
#  * the ``estimatedDelivery.date`` format — an unparseable value would silently
#    become ``None``, so normalize_parcel warns when it cannot parse a present
#    date.
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
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
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
            return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
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
        "text": f"{round(length)} x {round(width)} x {round(height)} cm",
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


def _moment(value: Any, zone: tzinfo) -> tuple[datetime, bool, str] | None:
    """Return ``(aware datetime, date_only, text)`` for a carrier time, or ``None``.

    A naive time or a bare date gets ``zone``; an aware time keeps its offset
    and, when it came in as a string, its own spelling.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        moment = datetime.combine(value, time.min, tzinfo=zone)
        return moment, True, moment.isoformat()
    elif isinstance(value, str) and value:
        try:
            if len(value) == 10:
                moment = datetime.combine(
                    date.fromisoformat(value), time.min, tzinfo=zone
                )
                return moment, True, moment.isoformat()
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo:
            return parsed, False, value
    else:
        return None
    moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)
    return moment, False, moment.isoformat()


def _end_of_day(moment: datetime, zone: tzinfo) -> datetime:
    local = moment.astimezone(zone)
    return datetime.combine(local.date(), time(23, 59, 59), tzinfo=zone)


def planned_window(
    start: Any, end: Any, *, zone: tzinfo
) -> tuple[str | None, str | None]:
    """Return ``(planned_from, planned_to)`` in the canonical window shape.

    ``start`` and ``end`` are ISO strings, dates or datetimes, or ``None``; an
    epoch number must be converted first (see ``to_iso_timestamp``). A window
    keeps both ends. One moment with a time ends at ``23:59:59`` the same local
    day; a date covers ``00:00:00`` to ``23:59:59``; two dates run from the
    first day's start to the last day's end. Equal values are one moment,
    reversed values are swapped, and ``planned_to`` is never set without
    ``planned_from``. ``zone`` is the carrier's own zone: it dates naive times
    and bare dates and decides which day a moment ends on, so a ``Z`` moment
    still ends on the carrier's local day. When nothing is left of that day
    after the moment, there is no ``planned_to``.
    """
    first = _moment(start, zone)
    last = _moment(end, zone)
    if first is None:
        first, last = last, None
    if first is None:
        return None, None

    def closing(moment: tuple[datetime, bool, str]) -> datetime:
        return _end_of_day(moment[0], zone) if moment[1] else moment[0]

    if last is not None and closing(last) < first[0]:
        first, last = last, first
    if last is not None and closing(last) == first[0]:
        last = None

    if last is None:
        end_of_day = _end_of_day(first[0], zone)
        return first[2], end_of_day.isoformat() if end_of_day > first[0] else None
    return first[2], closing(last).isoformat() if last[1] else last[2]


_NO_WINDOW_STATUSES = frozenset(
    {ParcelStatus.AT_PICKUP_POINT, ParcelStatus.RETURNING, ParcelStatus.DELIVERED}
)


def planned_for_status(
    status: ParcelStatus, planned_from: str | None, planned_to: str | None
) -> tuple[str | None, str | None]:
    """Empty the delivery window once the parcel is at its destination or done."""
    if status in _NO_WINDOW_STATUSES:
        return None, None
    return planned_from, planned_to


def is_pickup(
    route_flag: bool | None,
    status: ParcelStatus,
    event_statuses: Iterable[ParcelStatus | None] = (),
) -> bool:
    """Whether the delivery route ends at a pickup point.

    The carrier's own route flag wins; otherwise the parcel having reached
    ``AT_PICKUP_POINT`` at any point counts, so the value survives collection.
    """
    if route_flag:
        return True
    return status is ParcelStatus.AT_PICKUP_POINT or any(
        event is ParcelStatus.AT_PICKUP_POINT for event in event_statuses
    )


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
    * ``delivered`` is ``status is DELIVERED``; ``delivered_at`` only then.
    * ``planned_from`` / ``planned_to`` come from :func:`planned_window` and are
      emptied by :func:`planned_for_status`.
    * ``pickup`` comes from :func:`is_pickup` and stays ``True`` after
      collection; ``pickup_point`` is filled only when ``pickup``.
    * ``weight`` is kilograms, ``dimensions`` centimetres (see
      :func:`format_dimensions`).
    * ``history`` is ``None`` when the option is off — the key still exists.
    """
    tracking_code = raw.get("trackingNumber")
    status_code = raw.get("status")
    status = map_parcel_status(status_code)
    delivered = status is ParcelStatus.DELIVERED

    # Helthjem reports a single estimated-delivery value, a date or a moment.
    eta = raw.get("estimatedDelivery") or {}
    eta_date = eta.get("date")
    planned_from, planned_to = planned_for_status(
        status, *planned_window(to_iso_timestamp(eta_date), None, zone=_ZONE)
    )
    # Pre-release: the date *format* is unconfirmed. If a value is present but we
    # cannot parse it, it would silently become ``None`` — warn so a real parcel
    # tells us the real format (see _warn_observed_value).
    if eta_date and planned_from is None and planned_to is None:
        if parse_iso(to_iso_timestamp(eta_date)) is None:
            _warn_observed_value("estimatedDelivery.date", eta_date)

    # No top-level delivered timestamp — take it from the delivered event.
    delivered_at = _delivered_at(raw.get("events")) if delivered else None

    service_point = raw.get("servicePoint") or {}
    pickup = is_pickup(
        bool(service_point),
        status,
        (
            map_event_status(event.get("status"))
            for event in raw.get("events") or []
            if isinstance(event, dict)
        ),
    )

    # DOORMAT and MAILBOX are confirmed on real parcels; anything else is a
    # value we have not seen, so only those two stay quiet.
    delivery_point = raw.get("deliveryPoint") or {}
    if delivery_point.get("type") not in CONFIRMED_DELIVERY_POINT_TYPES:
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
        "planned_from": planned_from,
        "planned_to": planned_to,
        "pickup": pickup,
        "pickup_point": (service_point.get("name") or None) if pickup else None,
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
    filter_type = options.get(CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE)
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(UTC) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
