# Working in this repository

Home Assistant custom integration for **Helthjem** parcel tracking. Distributed
via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
Account-less (`track_parcel` / `untrack_parcel` services). No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| ship anything while below 1.0.0 (reconstructed, no real parcel) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed enum/shape |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client) | *Deliberate skill divergences* |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific notes

Helthjem is a Norwegian home-delivery carrier (built on Amedia's newspaper
network) that webshops pick at checkout. Overlaps with Bring/Posten and PostNord
on Norwegian parcels.

### Endpoint — keyless GraphQL
- `POST https://services.helthjem.no/graphql` — the backend
  `helthjem.no/sporing/` uses. **No auth**: the parcel reference alone is the
  input (`ref` variable). We send `Origin` + `Referer` set to the consumer site
  because the server checks them. Response is `application/json` (read with
  `response.json(content_type=None)` for robustness).
- The one query (`const.TRACKING_QUERY`, `getParcelTrackingDetails(parcelReference:)`)
  **was reconstructed by probing the live schema, not copied** — introspection is
  disabled (`__schema`/`__type` rejected), so field/type names were mapped from
  Apollo's field-validation error messages ("Cannot query field X", "Did you
  mean"). **If you extend the query, do it the same way.**

### Not-found vs error
- Unknown / not-yet-scanned ref → HTTP 200, `data.getParcelTrackingDetails ==
  null`, **no** `errors` → client returns `None` (normal, not an error).
- A GraphQL failure (schema drift, server error) → HTTP 200 with a top-level
  `errors` array → client **raises** `HelthjemApiError`, so the coordinator falls
  back to the cached payload rather than dropping the parcel.

### Payload → canonical (`getParcelTrackingDetails`)

| Canonical | Helthjem field | Notes |
|---|---|---|
| `barcode` | `trackingNumber` | |
| `status` / `raw_status` | `status` | `EventStatusType` enum; `raw_status` **is** the enum value (no separate human text at parcel level) |
| `history[]` | `events[]` | `{createdAt, status, location, message.description}`; event `status` is the **same** enum, so one map serves both |
| `delivered_at` | — | newest event whose status maps to `DELIVERED` (`_delivered_at`) |
| `planned_from` | `estimatedDelivery.date` | a single **date**, never a window → `planned_to` always `None` |
| `pickup` / `pickup_point` | `servicePoint.name` | present when routed to a service point |
| `url` | — | built from the ref: `helthjem.no/sporing/?trackingReference=…` |

- Timestamps are ISO strings (`createdAt` is `String!`); no epoch handling.
- **Not exposed → `None`**: `sender`, `receiver`, `weight`, `dimensions`. A
  heavier `getParcelDetails` field *does* carry weight/dimensions but returns a
  non-null object for an unknown ref (a poor not-found signal), so we deliberately
  use only the leaner `getParcelTrackingDetails`.

### Provisional (pre-1.0)
Reconstructed without a real parcel payload, so two things are unconfirmed and
collected via one-shot WARNINGs (issue link): the **`EventStatusType` vocabulary**
(`_STATUS_MAP` is a best-effort guess — introspection is off; `map_parcel_status`
/ `map_event_status` warn per unmapped value) and **`DeliveryPointType`**
(`_warn_observed_value("deliveryPoint.type", …)` logs each distinct value, since
it may be a cleaner pickup signal than the status). Remove those and confirm
`_STATUS_MAP` once a real parcel is observed end to end.

## Options and reloads — account-less model

The options flow is one sectioned form; changes apply without a restart.
Account-less carriers (this one) use the **update-listener** model (retunes
`coordinator.update_interval` + `async_request_refresh()`). Account-based carriers
instead call `async_schedule_reload` with **no** listener (combining the two is
deprecated, error in HA 2026.12+). The user-tunable poll interval is a deliberate
HACS divergence (see CONVENTIONS.md).

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types) | **yes** |
| `const.py` (domain, URLs, `TRACKING_QUERY`, `ParcelStatus`, option keys) | partly (URLs, query) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`) | no |

`parcels.py` is free of I/O and HA objects so the per-carrier part stays
unit-testable. Config: `ConfigEntry.runtime_data` (typed, no `hass.data`),
`PARALLEL_UPDATES = 0`, coordinator takes `config_entry=entry`.
`aiohttp.ClientError` is caught **per parcel** in the gather loop (one bad parcel
doesn't fail the poll) but **not** around the whole update (coordinator wraps
that). Entities: `has_entity_name` + `translation_key`, `icons.json`, translated
units, `_attr_attribution`, `_unrecorded_attributes` on anything with a parcel
list or `raw`. Over-redact diagnostics.

## Tests on Windows

`tests/conftest.py` carries two Windows-only shims (no-ops elsewhere):
`disable_socket` is neutralised (Windows event loops need AF_INET socketpairs;
the 127.0.0.1 allowlist stays) and HA's `AsyncResolver` is swapped for
`ThreadedResolver` (aiodns refuses the Proactor loop). Do not remove them
"because CI passes" — CI is Linux, development is Windows.

## Running tests

```
python -m pytest tests/ --cov=custom_components.helthjem
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; `docs/api/` is gitignored (local reverse-engineering notes).
