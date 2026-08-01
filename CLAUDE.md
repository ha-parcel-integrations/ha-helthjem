# Working in this repository

This is a Home Assistant custom integration for **Helthjem** parcel
tracking. Distributed via HACS; not part of HA core. It is one carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite and
publishes the same canonical parcel shape, statuses and events as the others,
so the aggregator and cross-carrier dashboards can read every carrier
identically.

It was generated from **ha-carrier-template**. Everything outside the
*Carrier-specific notes* section is suite-wide; when in doubt, check the
template or a sibling repo rather than inventing something new.

## Always consult HA developer documentation

Home Assistant's integration patterns evolve continuously. **Do not rely on
memory of past patterns** — fetch the canonical page before changing a topic
area, and check the developer blog before introducing anything you only "know"
from training data.

| When you change | Fetch first |
|---|---|
| Entity properties, naming, lifecycle, attributes | https://developers.home-assistant.io/docs/core/entity/ |
| Sensor specifics (state/device classes, units) | https://developers.home-assistant.io/docs/core/entity/sensor |
| Config flow, options flow, reauth, reconfigure | https://developers.home-assistant.io/docs/config_entries_config_flow_handler |
| DataUpdateCoordinator pattern | https://developers.home-assistant.io/docs/integration_fetching_data |
| Quality scale rules | https://developers.home-assistant.io/docs/core/integration-quality-scale |
| Diagnostics | https://developers.home-assistant.io/docs/core/integration/diagnostics |
| Translations | https://developers.home-assistant.io/docs/internationalization/core |

Recent developer-facing changes worth checking before introducing a pattern
from training data:

- https://developers.home-assistant.io/blog — API deprecations, new patterns,
  breaking changes. Recent posts trump older recollection.
- https://github.com/home-assistant/architecture/discussions — design decisions
  in flight that have not reached stable docs yet.

Branding is handled by the local `custom_components/helthjem/brand/`
folder (HACS reads `icon.png` from it). The official `home-assistant/brands`
repo is for HA Core integrations and does not apply here.

## Carrier-specific notes

Helthjem is a Norwegian home-delivery carrier (built on Amedia's newspaper
network) that webshops pick at checkout. It overlaps with Bring/Posten and
PostNord on Norwegian parcels.

### Endpoint — keyless GraphQL

- `POST https://services.helthjem.no/graphql` — the same backend
  `https://helthjem.no/sporing/` uses. **No auth**: the parcel reference alone
  is the input, sent as the `ref` GraphQL variable. We send `Origin` and
  `Referer` set to the consumer site because the server checks them.
- Response is `application/json`. We read it with `response.json(content_type=
  None)` for robustness, though it does send the right content type.
- The one query lives in `const.TRACKING_QUERY` and hits the
  `getParcelTrackingDetails(parcelReference:)` field. **It was reconstructed by
  probing the live schema, not copied from any client** — GraphQL introspection
  is disabled on this endpoint (`__schema`/`__type` are rejected), so the field
  and type names were mapped by reading Apollo's field-validation error messages
  (`Cannot query field X`, `Field Y must not have a selection …`, the "Did you
  mean" hints). If you extend the query, do it the same way.

### Not-found vs error

- Unknown / not-yet-scanned reference → HTTP 200 with
  `data.getParcelTrackingDetails == null` and **no** `errors`. The client turns
  that into `None` (a normal, expected state — never an error).
- A GraphQL failure (schema drift, server error) → HTTP 200 with a top-level
  `errors` array. The client **raises** `HelthjemApiError` on those, so the
  coordinator falls back to the cached payload rather than dropping the parcel.

### Payload → canonical (`getParcelTrackingDetails`)

| Canonical | Helthjem field | Notes |
|---|---|---|
| `barcode` | `trackingNumber` | |
| `status` / `raw_status` | `status` | `EventStatusType` enum; `raw_status` is the enum value itself (no separate human text at parcel level) |
| `history[]` | `events[]` | `{createdAt, status, location, message.description}`; event `status` is the **same** `EventStatusType` enum, so one map serves both |
| `delivered_at` | — | no top-level field; taken from the newest event whose status maps to `DELIVERED` (`_delivered_at`) |
| `planned_from` | `estimatedDelivery.date` | a single **date**, never a window → `planned_to` is always `None` |
| `pickup` / `pickup_point` | `servicePoint.name` | present when the parcel routes to a service point |
| `url` | — | built from the reference: `helthjem.no/sporing/?trackingReference=…` |

- **Timestamps** are ISO strings (`createdAt` is `String!`); no epoch handling
  needed.
- **Not exposed here → `None`:** `sender`, `receiver`, `weight`, `dimensions`.
  A heavier `getParcelDetails(trackingReference:)` field *does* carry
  weight/dimensions, but it returns a non-null object for an unknown reference,
  making it a poor not-found signal — so we deliberately use only the leaner
  `getParcelTrackingDetails`. Revisit if weight/dimensions become worth a second
  call.

### Provisional — this is a pre-release (< 1.0.0)

Reconstructed without a real parcel payload, so two things are **unconfirmed**
and collected from real data via one-shot WARNING logs (with an issue link):

- **`EventStatusType` vocabulary** — `_STATUS_MAP` in `parcels.py` is a
  best-effort guess (the enum members can't be listed with introspection off).
  `map_parcel_status` / `map_event_status` warn once per unmapped value.
- **`DeliveryPointType`** — `_warn_observed_value("deliveryPoint.type", …)` in
  `normalize_parcel` logs each distinct value once, since it may turn out to be
  a cleaner pickup signal than the status.

Remove those pre-release warnings and confirm `_STATUS_MAP` once a real Helthjem
parcel has been observed end to end.

## The canonical parcel contract

Every carrier publishes parcels through `normalize_parcel` in `parcels.py`
with **exactly** these top-level keys, in this order:

`carrier`, `barcode`, `sender`, `receiver`, `status`, `raw_status`,
`delivered`, `delivered_at`, `planned_from`, `planned_to`, `pickup`,
`pickup_point`, `url`, `weight`, `dimensions`, `history`, `raw`.

- A key the carrier does not expose is `None` — **never omitted**. Consumers
  read the key unconditionally.
- Carrier-specific extras live under `raw`. The aggregator strips `raw`, so
  anything that must survive aggregation has to be top-level.
- `status` is the canonical `ParcelStatus` enum; `raw_status` is the carrier's
  own text. Do not put the carrier's string on `status`.
- **Units**: `weight` in kilograms (float); `dimensions` in centimetres as
  `{length, width, height, text}` where `text` is `"L x W x H cm"` (integers,
  lowercase `x`). Convert before normalising if the carrier reports grams or
  millimetres.
- **Sort contract**: incoming ascending on `planned_from`, delivered descending
  on `delivered_at`, missing timestamps always last (`sort_parcels_by_ts`).
- Summary sensors expose the list under the `parcels` attribute — never
  `shipments`.

`test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards
the key set. Changing it is a suite-wide change: every carrier plus the
aggregator, together.

## Events

Fired on the HA bus by the coordinator, and exposed as no-code device triggers
via `device_trigger.py`:

| Event | When |
|---|---|
| `helthjem_parcel_registered` | A new, not-yet-delivered barcode appears |
| `helthjem_parcel_status_changed` | Canonical status changed (carries `old_status` / `new_status`) |
| `helthjem_parcel_delivered` | A parcel reached `delivered` |
| `helthjem_parcel_delivery_time_changed` | `planned_from` / `planned_to` changed |

Rules that are easy to break and must not be:

- **Events are suppressed on the very first refresh** (`_known_state is None`).
  Without this, every HA restart floods users with "registered" events for
  parcels that already existed.
- Events run over the **active + delivered set combined**, so the terminal hop
  is visible in one pass.
- The hop **to** `delivered` fires only `_parcel_delivered`, never also
  `_parcel_status_changed`. A barcode first seen already-delivered fires
  nothing.
- An ETA going `value → null` is **intentionally silent** — the carrier merely
  lost the window; not worth waking someone up for.
- Every payload is the full normalised parcel plus `device_id` (resolved once
  and cached in `_cached_device_id`). `device_id` is what lets device triggers
  filter per hub.

## Architecture rules

- **`ConfigEntry.runtime_data`** with a typed dataclass; no `hass.data`.
- **The first refresh runs in `__init__.py`, before
  `async_forward_entry_setups`.** Raising `ConfigEntryNotReady` from a
  *forwarded* platform is too late for HA to catch: it logs a warning and
  half-sets-up the entry, and users end up with some platforms and no sensors.
  Never move the first refresh into a platform.
- **`PARALLEL_UPDATES = 0`** in every platform — the coordinator already
  handles fan-out.
- The coordinator takes `config_entry=entry`, so `self.config_entry` works.
- `aiohttp.ClientError` is deliberately **not** caught around the whole update
  — `DataUpdateCoordinator` wraps it into `UpdateFailed` already. It *is*
  caught per parcel in the gather loop, so one bad parcel does not fail the
  whole poll.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove(entity_id)` when a barcode drops out of the
  coordinator data. Self-removal races with coordinator-listener cleanup and
  leaves ghost entities behind.
- **The setup-time stale-entity sweep in `sensor.py` is scoped to
  `entity_entry.domain == "sensor"`** and skips every unique_id in
  `non_parcel_unique_ids`. Without the domain check it deletes the refresh
  button; without the exclusion set it deletes the summary and diagnostic
  sensors. When you add a non-parcel sensor, add its unique_id to that set.
- **`has_entity_name = True` + `translation_key`** on every entity. Names come
  from `strings.json` and the translation files — no `_attr_name`. Icons come
  from `icons.json` — no `_attr_icon`. Units come from
  `entity.sensor.<key>.unit_of_measurement` — no
  `_attr_native_unit_of_measurement`.
- **`_unrecorded_attributes`** on anything carrying a parcel list or a `raw`
  payload, so the recorder's long-term tables stay small.
- `_attr_attribution` on every entity.
- **Unmapped statuses log a one-shot WARNING** per distinct value with a
  copy-paste `issues/new` link; users report them through the *Unrecognised
  parcel status* issue template. That is how the status map grows.
- Diagnostics redact every identifying field — they get pasted into public
  issues. Over-redact rather than under-redact.
- Network calls return raw JSON dicts; there is no DTO layer.

## Options and reloads

The options flow is **one sectioned form** (`data_entry_flow.section`), and
changes apply without a restart. Two models, do not mix them:

- **Account-less carriers** (this one) apply changes live: an update listener
  retunes `coordinator.update_interval` and calls `async_request_refresh()`, so
  added and removed parcel sensors appear immediately.
- **Account-based carriers** call `async_schedule_reload` on submit and
  register **no** update listener. Combining an update listener with a
  reload-on-update flow is deprecated today and an error in HA 2026.12+ — see
  the [config_entry_listener deprecation](https://developers.home-assistant.io/blog/2026/05/07/config-entry-listener-together-with-reloading-methods/).

A user-tunable polling interval is a **deliberate divergence** from the HA Core
rule that polling intervals are not configurable: that rule targets core
integrations, and in a HACS parcel tracker a tunable cadence is a wanted
feature. Carriers that throttle or soft-ban unusual traffic are generated with
a fixed cadence instead and have no polling option at all.

## Module layout

| File | Contains | Carrier-specific? |
|---|---|---|
| `api.py` | HTTP client, error types | **yes** |
| `const.py` | Domain, URLs, `ParcelStatus`, option keys | **partly** (URLs) |
| `parcels.py` | Status map, `normalize_parcel`, history, sort, filters — pure functions | **partly** (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` | Fetching, caching, event firing | mostly not |
| `config_flow.py` | Setup + options flow | **partly** (code validation) |
| `sensor.py` / `button.py` / `calendar.py` | Entities | no |
| `device_trigger.py` | Device triggers | no |
| `diagnostics.py` | Redacted diagnostics | **partly** (`TO_REDACT`) |
| `services.py` | `track_parcel` / `untrack_parcel` (account-less only) | no |

`parcels.py` is deliberately free of I/O and HA objects: the part you rewrite
per carrier stays unit-testable without spinning up Home Assistant.

## Tests on Windows

`tests/conftest.py` carries two Windows-only shims (both no-ops elsewhere):
pytest-homeassistant-custom-component's `disable_socket` is neutralised
(Windows event loops need AF_INET socketpairs; the connect-time 127.0.0.1
allowlist stays), and HA's hardcoded aiohttp `AsyncResolver` is swapped for
`ThreadedResolver` (aiodns refuses the Proactor loop). Do not remove them
"because CI passes" — CI is Linux, development happens on Windows.

## Docs and README

- The README stays **lean and installer-first** (suite house style): no
  per-entity `## Buttons` / `## Calendar` sections; the device-trigger option
  is one sentence folded into **Events**. This file documents everything else.
- **A code change updates the docs in the same commit** where behaviour
  changes — README, this file, and `docs/`.
- `docs/api/` is gitignored: reverse-engineering notes stay local.

## Workflow, commits, releases

See `ha-parcel-integrations/.github/CONVENTIONS.md` for the shared rules
(single-line commit messages, no `v` prefix on tags, semver, maintainer-only
merges, user-facing release notes). Not repeated here.

## Running tests

```
python -m pytest tests/ --cov=custom_components.helthjem
```

Coverage must stay **above 95%** (the silver `test-coverage` rule). Run before
committing.
