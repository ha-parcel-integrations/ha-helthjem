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

**Structure, options flow, dynamic polling and module layout are suite-wide**
and identical in every carrier — the authoritative spec is
[`ha-carrier-template/scaffold/CLAUDE.md`](https://github.com/ha-parcel-integrations/ha-carrier-template/blob/main/scaffold/CLAUDE.md).
Where this repo diverges from it, that is recorded below under
*Divergences from the scaffold*.

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

## Divergences from the scaffold

Everything not listed here follows the scaffold exactly.

*Module layout* — `api.py` is a **GraphQL** client (`TRACKING_QUERY` lives in
`const.py`), not the stock REST client. A GraphQL `errors` array raises, so the
coordinator falls back to the cached payload rather than dropping the parcel.

## Running tests

```
python -m pytest tests/ --cov=custom_components.helthjem
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file in the same commit;
the API reference now lives in the private `carrier-research/helthjem/api/`,
not in this repo.
