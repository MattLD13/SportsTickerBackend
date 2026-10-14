# Device Stream V1

The main Pi uses HTTP for registration and its first snapshot. It uses WebSocket for later display updates.

## Connection

Connect to `WS /api/v2/tickers/<ticker_id>/stream` with the `ticker-v2` WebSocket subprotocol.

Send both `stream_id` and `after_seq` query values to resume. Omit both values for a new session.

The server accepts only registered ticker IDs. This route uses the same read access as the current public data snapshot route. Device-specific credentials remain future security work.

## Envelope

Each JSON message contains `protocol_version`, `type`, `stream_id`, `seq`, `base_seq`, and `server_time`.

`protocol_version` is `1`. `stream_id` changes when the backend process restarts. Sequence values increase per ticker within one stream.

`server_time` uses UTC ISO 8601. Clients use sequence values for order and timestamps for age.

## Message types

| Type | Fields | Meaning |
|---|---|---|
| `snapshot` | `payload` | Full effective V2 display projection. |
| `delta` | `changes`, `removed` | Changed top-level projection fields and removed field names. |
| `ready` | None | The server accepted the client's current replay cursor. |

Snapshots use the same payload as `GET /api/v2/tickers/<ticker_id>/data`.

A delta has `base_seq` equal to the client's current sequence. Its `seq` equals `base_seq + 1`.

## Replay and recovery

The server keeps 256 deltas per ticker. It sends replay when the stream ID and cursor match retained history.

The server sends a full snapshot when a stream ID changes, a cursor expires, or a client queue fills. The client drops duplicate sequence values.

The client drops its cursor after a gap or malformed delta. It reconnects without a cursor and receives a full snapshot.

The server bounds each client queue to 32 messages. Snapshot writes and HTTP mutations wake the projector for affected tickers.

The projector checks active tickers once per second for time-based schedule and event expiry changes.

The server sends WebSocket Ping frames every 20 seconds. The client library answers Ping frames with Pong frames. Hypercorn does not expose a Pong timeout setting.

HTTP heartbeat and command acknowledgement routes remain independent from stream traffic. The Mini keeps its HTTP snapshot path.
