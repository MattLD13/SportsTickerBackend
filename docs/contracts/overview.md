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

Racing includes explicit class cards and scoped race-control signals. Read [the racing display contract](racing-flags.md).

Scoreboard data includes integer `competition_stage`: `0` for regular season, `1` for playoffs, and `2` for finals.
The sports display projector resolves this field from provider season and tournament round metadata.
Game status and completion do not determine the tournament round.
All playoff rules use this field. Values `1` and `2` both select postseason rules.
The NHL live feed supplies its normalized stage before the shared projection applies overtime rules.
When NHL omits standard-strength counts, stage `0` uses three skaters in overtime. Stages `1` and `2` use five.
Explicit live manpower counts take priority over standard-strength counts.
Six and Mini use silver rules for `1` and gold rules for `2`.
Six applies these colors to scrolling pane boundaries. Pinned scoreboards retain their normal appearance.
Finals gold takes priority where two scrolling panes share a boundary.

| Sports | Stage source |
|---|---|
| NFL, MLB, NHL, NBA, FBS, FCS, and college basketball | ESPN season and competition round metadata. |
| Premier League, Championship, MLS, Champions League, and FA Cup | FotMob tournament rounds. All FA Cup rounds use knockout rules. |
| PGA golf | FedEx St. Jude and BMW Championship use `1`. TOUR Championship uses `2`. Other events use `0`. |
| NASCAR Cup | The official `playoff_round` flag selects `1`. The championship race selects `2`. |
| F1, IndyCar, IMSA, and WEC | `0`. These series do not use a playoff bracket. |

An ordinary tournament's final round or race completion does not select stage `2`.

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


## Stock symbol search

`GET /api/v2/catalog/stocks?q=<company-or-symbol>` returns confirmed US symbol matches.
The response contains `stocks`, with `symbol` and `name` for each match.
An empty query returns an empty list. Queries contain at most 60 characters.
The server returns at most 12 matches, with an exact symbol match first.
The server caches search results for one hour and keeps provider keys on the server.
An unavailable search returns HTTP 503 with `stock_search_unavailable`.
The controller adds a stock only after the user selects a returned symbol.
The controller shows the selected symbol immediately and preserves manual list order.
New custom quotes interrupt the market sweep. Each completed quote becomes available immediately.
The stock snapshot job reads the shared quote cache every two seconds.
The source retains its existing upstream quote cadence and request pacing.
