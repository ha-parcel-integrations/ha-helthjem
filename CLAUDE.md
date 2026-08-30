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
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| ship anything while below 1.0.0 (reconstructed, no real parcel) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed enum/shape |
| consider "fixing" a lint/pattern the skill flags (inline client) | *Deliberate skill divergences* |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**API mechanics live in `carrier-research/helthjem/api/` (private research repo)** — the keyless
GraphQL endpoint, the `getParcelTrackingDetails` query, the not-found-vs-error
signalling, the payload→canonical mapping and the `EventStatusType` vocabulary. Do
not duplicate them here.

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific decisions (integration only)

Helthjem is a Norwegian home-delivery carrier (Amedia's newspaper network) that
webshops pick at checkout; overlaps with Bring/Posten and PostNord.

- **The GraphQL query was reconstructed by probing the live schema** (introspection
  is disabled) — see `carrier-research/helthjem/api/` before extending it; extend it the same way.
- **We deliberately use the leaner `getParcelTrackingDetails`, not
  `getParcelDetails`** — the latter carries weight/dimensions but returns a
  non-null object for an unknown reference, making it a poor not-found signal.
  Revisit if weight/dimensions become worth a second call. `sender`/`receiver`/
  `weight`/`dimensions` stay `None`; `planned_from` is a single date (`planned_to`
  always `None`). Reflected in `const.py`'s `CAPABILITIES` (feeds the docs
  site's comparison table) — keep the two in agreement if that ever changes.
- **Provisional (pre-1.0):** the status vocabulary is a best-effort guess
  collected via one-shot WARNINGs (introspection is off); `DeliveryPointType`
  values are logged too since one may be a cleaner pickup signal than the status.
  The `estimatedDelivery.date` **format** is unconfirmed — a value we can't parse
  would silently become `None`, so `normalize_parcel` logs a one-shot WARNING when
  a present date fails to parse. Confirm once a real parcel is observed end to end.

## Options and reloads — account-less model

The options flow is one sectioned form; changes apply without a restart.
Account-less carriers (this one) use the **update-listener** model — the
listener just calls `async_request_refresh()`. Account-based carriers instead
call `async_schedule_reload` with **no** listener (combining the two is
deprecated, error in HA 2026.12+).

## Dynamic, status-driven polling

Unconditional — there is no user-facing interval option. `coordinator.py`
recomputes `update_interval` at the end of every refresh: 15 min ("hot") when
a tracked, not-yet-delivered parcel is `out_for_delivery` within an hour of
its estimated delivery time (or has none at all), 45 min ("mid") otherwise,
and `None` (fully suspended) when nothing is tracked or everything tracked is
delivered — polling resumes the moment `_async_options_updated` sees a parcel
added back. No polling at all between 00:00–06:00 local time except the two
daily anchor checks, plus a small per-entry stagger so installs don't all
poll on the same second. See `carrier-research/dynamic-polling.md` for the
full algorithm and `ha-carrier-template`'s `coordinator.py` for the reference
shape this mirrors.

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (GraphQL client, error types) | **yes** |
| `const.py` (domain, URLs, `TRACKING_QUERY`, `ParcelStatus`, option keys) | partly (URLs, query) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`) | no |

`parcels.py` is free of I/O and HA objects so the per-carrier part stays
unit-testable. Config: `ConfigEntry.runtime_data` (typed, no `hass.data`),
`PARALLEL_UPDATES = 0`, coordinator takes `config_entry=entry`. A GraphQL
`errors` array raises so the coordinator falls back to the cached payload rather
than dropping the parcel; `aiohttp.ClientError` is not caught around the whole
update (coordinator wraps it). Entities: `has_entity_name` + `translation_key`,
`icons.json`, translated units, `_attr_attribution`, `_unrecorded_attributes` on
anything with a parcel list or `raw`. Over-redact diagnostics.

## Running tests

```
python -m pytest tests/ --cov=custom_components.helthjem
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file in the same commit;
the API reference now lives in the private `carrier-research/helthjem/api/`,
not in this repo.
