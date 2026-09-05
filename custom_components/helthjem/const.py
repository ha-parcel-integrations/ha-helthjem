"""Constants for the Helthjem parcel tracker integration."""
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "helthjem"


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    **Do not extend or rename these members.** Every integration in the parcel
    suite publishes exactly this vocabulary on the ``status`` field of each
    normalised parcel, so cross-carrier automations and the aggregator can
    target ``status: out_for_delivery`` regardless of carrier. Listed in
    roughly the order a parcel moves through.
    """

    REGISTERED = "registered"               # Sender announced the parcel; not handed over yet
    IN_TRANSIT = "in_transit"               # In the carrier's network
    OUT_FOR_DELIVERY = "out_for_delivery"   # On a delivery vehicle today
    AT_PICKUP_POINT = "at_pickup_point"     # Ready to collect at a pickup location
    DELIVERED = "delivered"                 # Handed over
    RETURNING = "returning"                 # Failed delivery, going back to sender
    PROBLEM = "problem"                     # Carrier reports an exception/issue
    UNKNOWN = "unknown"                     # Raw status we have not mapped yet


PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]

# Every optional key the parcel contract defines. CAPABILITIES below must be a
# subset of this — it exists so a typo in CAPABILITIES fails a test instead of
# silently dropping this carrier off a table on the docs site.
KNOWN_CAPABILITIES = frozenset(
    {"weight", "dimensions", "delivery_window", "pickup_point", "url", "history"}
)

# Which optional contract fields this carrier's API actually populates — feeds
# the comparison table on the docs site. Keep in lockstep with
# normalize_parcel() in parcels.py: everything not listed here comes back as a
# literal None there. The leaner getParcelTrackingDetails query Helthjem uses
# never carries weight or dimensions.
CAPABILITIES = frozenset({"delivery_window", "pickup_point", "url", "history"})

# Helthjem's consumer tracking backend is a **keyless GraphQL endpoint** — the
# same one https://helthjem.no/sporing/ calls. No account, no API key: the
# parcel reference alone is the input.
#
# * Transport: ``POST`` with a JSON body ``{"query": ..., "variables": {"ref"}}``,
#   ``Content-Type: application/json``. The server checks the ``Origin`` /
#   ``Referer``, so both are sent as the consumer site.
# * The single query is :data:`TRACKING_QUERY` below, hitting the
#   ``getParcelTrackingDetails(parcelReference:)`` field. Reconstructed from the
#   live schema (introspection is disabled, so it was mapped by probing Apollo's
#   field-validation errors), not copied from any client.
# * Unknown / not-yet-scanned reference: HTTP 200 with
#   ``data.getParcelTrackingDetails == null`` and **no** ``errors`` — a normal,
#   expected state the client turns into ``None``.
# * GraphQL errors arrive as HTTP 200 with a top-level ``errors`` array; the
#   client raises on those.
TRACKING_API_URL = "https://services.helthjem.no/graphql"

# Consumer deep link surfaced on each parcel's ``url`` field. Best-effort: the
# tracking page is a single-page app keyed on the reference.
TRACKING_URL = "https://helthjem.no/sporing/?trackingReference={tracking_code}"

# Origin/Referer the GraphQL backend expects (it is the consumer site's own
# API). Sent verbatim on every request.
TRACKING_ORIGIN = "https://helthjem.no"
TRACKING_REFERER = "https://helthjem.no/sporing/"

# The one query the integration sends. ``getParcelTrackingDetails`` is the
# purpose-built tracking type: it returns ``null`` for an unknown reference
# (the clean not-found signal) and carries status, the event timeline, the ETA
# and — when the parcel routes to one — the service (pickup) point.
#
# Fields Helthjem's schema does **not** expose here (weight, dimensions, sender
# name, receiver name) are left ``None`` on the canonical parcel, mirroring how
# DHL-NL handles the same gaps. A heavier ``getParcelDetails`` field does carry
# weight/dimensions but returns non-null for unknown references, so it is a poor
# not-found signal and is deliberately not used.
TRACKING_QUERY = """
query ParcelTracking($ref: String!) {
  getParcelTrackingDetails(parcelReference: $ref) {
    trackingNumber
    status
    estimatedDelivery {
      date
    }
    servicePoint {
      name
      address
    }
    deliveryPoint {
      type
    }
    events {
      createdAt
      status
      location
      message {
        description
      }
    }
  }
}
"""

# Tracked parcels live in the config entry options as a list of
# ``{tracking_code}`` dicts — this carrier has no account or parcel feed, so the
# user enters the codes themselves. Kept as dicts so future per-parcel fields
# slot in without an options migration.
CONF_PARCELS = "parcels"
CONF_TRACKING_CODE = "tracking_code"

# Delivered-parcels retention: keep delivered parcels visible for the last N
# days, or keep only the N most recent — identical across the suite.
CONF_DELIVERED_FILTER_TYPE = "delivered_filter_type"
CONF_DELIVERED_FILTER_AMOUNT = "delivered_filter_amount"
DEFAULT_DELIVERED_FILTER_TYPE = "days"
DEFAULT_DELIVERED_FILTER_AMOUNT = 7

# Dynamic, status-driven polling — unconditional, no user-facing interval
# option.
#
# Quiet window: no polling between these local hours except the two anchors
# below, for overnight / end-of-day catch-up.
QUIET_WINDOW_START_HOUR = 0
QUIET_WINDOW_END_HOUR = 6

# Cadence while polling is active (minutes). Hot = at least one tracked,
# not-yet-delivered parcel is out_for_delivery within HOT_LOOKAHEAD_HOURS of
# its planned_from (or has no planned_from at all); mid = anything else still
# in flight. This is a barcode-based coordinator (Section 2.1): when every
# tracked parcel is delivered, or nothing is tracked, polling stops entirely
# instead of falling to the mid tier — see coordinator.py's
# ``_hottest_tier_minutes``.
HOT_INTERVAL_MINUTES = 15
MID_INTERVAL_MINUTES = 45
HOT_LOOKAHEAD_HOURS = 1

# Small, stable per-install offset added to every computed interval so
# different installs don't all hit an anchor or tier boundary at the same
# second. Deterministic (hash of the config entry id), not random.
STAGGER_MINUTES = 7

# Per-parcel status history is opt-in and off by default, identical across the
# suite. Keep it off by default even when — as here — the timeline arrives in
# the same response and costs no extra request: it is a large attribute, and on
# carriers that need a second call per parcel the cost is real.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
