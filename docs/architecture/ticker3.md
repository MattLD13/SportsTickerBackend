# Ticker 3 backend design

Ticker 3 is a full rebuild of the server. It lives in `ticker3/`.
The current server in `sports_ticker/` is the behavior reference. Ticker 3 imports nothing from it.

## Goals

1. A new feature is one folder in `ticker3/features/`. The core names no feature.
2. A failed feature process stops only that feature. It does not stop the core or other features.
3. A feature update replaces its process with no gap in data.
4. A device downloads each screen layout once. After that, it receives only changed values.
5. Each upstream source is read once for all tickers that need it.

## Parts

| Part | Folder | Job |
|---|---|---|
| Contract | `ticker3/contract/` | Messages, templates, settings schemas, and their validation. Every other part imports it. |
| Worker SDK | `ticker3/sdk/` | The process host for one feature. It connects to the core, reads upstreams, and sends record changes. |
| Features | `ticker3/features/<name>/` | Upstream reads, records, and templates for one feature. A feature imports only the contract and the SDK. |
| Core | `ticker3/core/` | Fleet store, subscriptions, record store, composition, device streams, HTTP API, and the worker supervisor. The core imports no feature. |
| Player | `ticker3/player/` | The reference template player. It draws a screen from a template and values. Tests and previews use it. |

## Terms

| Term | Meaning |
|---|---|
| Feature | One kind of content, such as `weather` or `sports`. |
| App | One feature with its settings in the playlist of one ticker. |
| Subscription | One normalized feature config. All apps with the same config share one subscription. |
| Record | One item that a subscription produces. It has an ID, a template ID, values, tags, and an order number. |
| Screen | One record after the core resolves its references. A device draws a screen with a template. |
| Reference | A value that points to a record of another feature. The core resolves it. |

## Data flow

1. The app saves the playlist of a ticker. Each app has a feature and settings.
2. The core normalizes the settings with the schema of the feature.
3. The core expands the settings into subscriptions. A `fanout` list field gives one subscription for each item.
4. The core sends the full subscription set to the feature worker.
5. The worker reads its upstreams on its own schedule. It sends a `sync` for each new subscription and a `delta` when records change.
6. The core stores the records. Then it composes the screens of each affected ticker.
7. The core sends each connected device the changed values only.

The core never polls a worker. The worker owns the upstream timing, because it knows the upstream limits and push channels.

## Features share data through the core

A record value can be a reference:

```json
{"weather": {"$ref": {"feature": "weather", "config": {"latitude": 19.4, "longitude": -99.09}, "record": "now"}}}
```

1. The core normalizes the reference config with the schema of the target feature.
2. The core adds that config to the subscriptions of the target feature.
3. During composition, the core replaces the value with the values of the target record. Each key gets the prefix `weather.`.
4. If the target record is missing, the core adds no keys. The template hides the parts that need them.

A worker never connects to another worker. A failed target feature removes only the referenced values.

## Built-in features

The core runs the `clock` feature itself. The clock has no upstream, so a process for it has no value.
A device draws the time from its own clock. The clock record carries only the time zone and the format.

## Worker protocol

The core listens on one Unix socket. Each worker connects to it.
Each message is one JSON object on one line. A line must be at most 4 MiB.

| Direction | Type | Content |
|---|---|---|
| worker to core | `hello` | Protocol version, feature name, release, process ID, and manifest. |
| core to worker | `welcome` | Acceptance, or the reason for refusal. |
| core to worker | `subscribe` | The full set of subscriptions, as key to config. |
| worker to core | `sync` | All records of one subscription. |
| worker to core | `delta` | Changed and removed records of one subscription. |
| worker to core | `health` | Status every 5 seconds, with the error of each failed subscription. |
| core to worker | `wake` | A request to read the given subscriptions now. |
| core to worker | `drain` | A request to stop after the last message. |

A subscription key is the first 16 hex digits of the SHA-256 of the canonical config JSON.

## Supervisor

The core starts each worker as a separate process in its own session.

- If a worker exits or stops its health messages for 20 seconds, the supervisor starts it again with backoff.
- If a release crashes 3 times in 30 minutes, the supervisor marks it bad and starts the previous release.
- To deploy a release, the supervisor starts it next to the active release.
  The new release becomes active after it syncs each subscription.
  Then the old release gets `drain`. Devices see no gap.
- If the new release fails the trial, the old release stays active and the new release is marked bad.
- Workers keep running when the core restarts. They connect again, and the core adopts them.
- If a worker has no core for 10 minutes, it stops.

## Device protocol

A device opens a WebSocket at `/v3/stream` and sends `hello` with its token, panel size, and template bundle hash.

| Type | Content |
|---|---|
| `templates` | The templates for the panel size of the device. The server sends them only when the bundle hash differs. |
| `screens` | The full ordered screen list. The server sends it after `hello`. |
| `delta` | Changed values of each changed screen, removed screen IDs, and the new order if it changed. |
| `ping` | A keepalive. The device answers `pong`. |

A score change sends only the changed values, for example about 60 bytes.

## Templates

A template has one block for each panel size. A block has a box size, a flow, and a parts list.
A `scroll` flow joins screens into a moving strip. A `page` flow shows each screen for its dwell time.
A part can show or hide with a simple rule: `key`, `!key`, `key == value`, or `key != value`.
Game logic stays in the feature. It arrives as plain values.

## Storage

The core keeps tickers, tokens, and playlists in SQLite in WAL mode.
Device and app tokens are random. The store keeps only their SHA-256 hashes.

## Run

```bash
TICKER3_ADMIN_TOKEN=change-me python -m ticker3.core.main
```

`ticker3/core/main.py` lists the settings. The API listens on `127.0.0.1:5300` by default.

1. `POST /v3/tickers` with the admin token creates a ticker. The answer holds the device token and a pairing code.
2. `POST /v3/pair` with the code gives an app token.
3. `PUT /v3/tickers/{id}/apps` with the app token sets the playlist.
4. A device opens `/v3/stream` and sends `hello` with its device token.

## Validation

Each part has focused tests in `tests/python/ticker3/`.
Feature tests use recorded real payloads in `tests/fixtures/ticker3/`.
End-to-end tests start the real core, real worker processes, and a WebSocket device.
`tools/ticker3/preview.py` renders real 384x32 and 64x32 frames into `previews/ticker3/`.

## Measured results

These figures come from the live run on 2026-10-29.

| Fact | Value |
|---|---|
| Worker process memory | 28 to 31 MB each |
| Templates for a 64x32 panel | 2,468 bytes, sent once |
| Templates for a 384x32 panel | 4,201 bytes, sent once |
| Full screen list, 24 screens | 8,529 bytes, sent at connection |
| One score change | under 70 bytes |
| F1 track weather through a reference | joined about 1 second after start |
| Hot-swap deploy | no new `screens` message and no gap on the device |
