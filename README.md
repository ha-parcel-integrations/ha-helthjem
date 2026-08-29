# Helthjem Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-helthjem.svg)](https://github.com/ha-parcel-integrations/ha-helthjem/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Helthjem](https://helthjem.no) parcels. Helthjem is a Norwegian home-delivery carrier (built on Amedia's newspaper-distribution network) that many Norwegian webshops use. No account is needed — you enter the parcel reference yourself, just like on Helthjem's own tracking page, and the integration reads the same keyless endpoint that page uses.

> ⚠️ **Early release.** This integration was reconstructed from Helthjem's live tracking API without a real parcel to verify against, so the status vocabulary is still being confirmed. If you see an `unknown` status or a warning in the log asking you to report something, please [open an issue](https://github.com/ha-parcel-integrations/ha-helthjem/issues/new) — that is how the mapping is completed.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Helthjem parcels by tracking code — no account needed
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / …), Helthjem's own status code, the estimated delivery date and a tracking deep-link
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar with the estimated delivery dates
- `helthjem.track_parcel` / `helthjem.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2024.12 or newer
- A Helthjem parcel and its reference number (from the shipping
  confirmation email) — no account needed

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-helthjem` as an **Integration**.
3. Install **Helthjem** and restart Home Assistant.

### Manual

Copy `custom_components/helthjem` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Helthjem**. There is nothing to fill in: the hub is created immediately (Helthjem tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`helthjem.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking code is on your shipping confirmation email or the missed-delivery card.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |
| Polling | Refresh every | 30 min | How often Helthjem is checked. Slower is gentler on their API. |

## Removal

Standard HA removal applies: **Settings → Devices & Services → Helthjem → ⋮ → Delete**. Nothing is stored on Helthjem's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.helthjem_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.helthjem_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.helthjem_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.helthjem_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.helthjem_last_successful_update` | Diagnostic: when Helthjem was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

A **Deliveries** calendar entity is also created, showing estimated delivery
dates for active parcels — read-only, no extra API calls.

A **Refresh** button entity forces an immediate poll, without waiting for the
next scheduled interval.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `registered` | Announced / received by Helthjem |
| `in_transit` | In the sorting network |
| `out_for_delivery` | With the courier today |
| `at_pickup_point` | Waiting for you at a service point |
| `delivered` | Delivered |
| `returning` | Going back to the sender |
| `problem` | Helthjem reports an exception |
| `unknown` | Not yet scanned, or a status we have not mapped yet |

Helthjem's own status code is always available as `raw_status`. The mapping from
those codes onto this enum is still being confirmed against real parcels, so an
unmapped code shows as `unknown` and logs a one-time warning asking you to
report it.

## Events

The integration fires these on the event bus (also available as device triggers on the Helthjem device):

| Event | When |
|---|---|
| `helthjem_parcel_registered` | A new parcel appears in the active list |
| `helthjem_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `helthjem_parcel_delivered` | A parcel is delivered |
| `helthjem_parcel_delivery_time_changed` | The estimated delivery date changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `helthjem.track_parcel` | `tracking_code` | Start tracking a parcel |
| `helthjem.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.helthjem: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — Helthjem has not scanned it yet (their API returns no data for the reference until the first scan), or the reference is wrong. It will pick up automatically once scanned.
- **A status logs "Unrecognised Helthjem status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-helthjem/issues/new) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as the Helthjem consumer website. It is not affiliated with, endorsed by, or supported by Helthjem. Be gentle with the polling interval.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
