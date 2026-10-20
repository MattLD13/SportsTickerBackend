# Existing V2 contracts

This document describes the current contract. Source definitions remain authoritative.
It does not introduce runtime validation, generated models, or a new protocol.

The registration schema is not authoritative yet. It differs from defaults and accepted fields in the active registration route.
Read [the revised engineering SOW](../plans/engineering-sow.md) before adding runtime schema gates.

## Data response

Devices read `GET /api/v2/tickers/<ticker-id>/data`.
`sports_ticker/projections/data_api.py` owns the JSON envelope.
`sports_ticker/api/routes.py` owns route authorization and response construction.

| Field | Current meaning |
|---|---|
| `api_version` | The string `v2`. |
| `snapshot` | Ticker ID, revision, observation time, and stale state. |
| `settings` | Effective ticker display settings. |
| `content` | Content family keys containing ordered item lists. |
| `events` | Separate `alerts` and `news` overlay lists. |
| `health` | Provider health information. |
| `meta` | Backend metadata supplied to the projection. |

Each content item contains `id`, `family`, `kind`, `is_shown`, and `data`.
Each overlay contains `event_id`, `kind`, and `payload`.
Family data varies with the content kind. Read the projector and provider definitions before changing those fields.

## Settings and presentation

Stored selectable modes are `sports`, `stock`, `weather`, `music`, `flights`, `airports`, and `clock`.
Pairing is an effective output state. A pinned game uses `sports_presentation: pinned` within sports mode.
Alerts, news, connection loss, and updates use overlays.
Clients consume projected domain facts and explicit family and kind values.

Each ticker stores one ordered `custom_stock_symbols` array with up to 30 symbols.
The server trims symbols, converts them to uppercase, and removes duplicates.
`active_sports.stock_custom` selects this list. Existing market categories remain smart lists.
Custom stocks use the shared quote cache and retain their saved order.
The controller shares symbols as text. Pasting shared symbols copies them into the custom list of another ticker.

`meta.schedule.live_games` counts fresh visible live sports records in this ticker's snapshot.
It excludes other tickers and deduplicates game identifiers.
`meta.schedule.has_enabled_rules` identifies enabled schedule blocks or live-sports conditions for this ticker's supported modes.
Controller schedule override actions use this field. An inactive time window does not mean the schedule is empty.

## Source definitions

| Boundary | Source |
|---|---|
| Domain models | `sports_ticker/domain/models.py` and `sports_ticker/domain/snapshot.py` |
| Overlay events | `sports_ticker/domain/events.py` |
| Fleet persistence | `sports_ticker/fleet/repository.py` |
| JSON projection | `sports_ticker/projections/data_api.py` |
| HTTP routes | `sports_ticker/api/routes.py` |
| Pi response parsing | `ticker_core/protocol/model.py` |
| Pi polling | `ticker_core/protocol/client.py` and `ticker_core/protocol/polling.py` |
| Protocol validation coverage | `tests/python/protocol/` |

The HTTP snapshot route remains the Pi boot path. The main Pi uses Device Stream V1 for sequenced updates.
Snapshot revisions do not define stream ordering or replay. Provider WebSockets do not define the device stream contract.
Read [Device Stream V1](device-stream-v1.md) for its envelope and recovery rules.
