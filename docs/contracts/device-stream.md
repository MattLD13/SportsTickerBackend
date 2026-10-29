# Device stream

The main Pi uses HTTP for registration and its first snapshot. It uses WebSocket for later display updates.

## Connection

Connect to `WS /stream` with the `ticker` WebSocket subprotocol.

Send both `stream_id` and `after_seq` query values to resume. Omit both values for a new session.

The `X-Device-Token` header names the ticker. The server refuses a missing or unknown token.
It checks the token before the snapshot, and again at most every 5 seconds.

## Envelope

Each JSON message contains `type`, `stream_id`, `seq`, `base_seq`, and `server_time`.
The subprotocol names the message format, so a message has no version field.

`stream_id` changes when the backend process restarts. Sequence values increase per ticker within one stream.

`server_time` uses UTC ISO 8601. Clients use sequence values for order and timestamps for age.

An optional `timing.projected_at_ms` value records when the projection entered stream preparation.
It uses UTC Unix milliseconds. It does not affect sequence order or the display fingerprint.
The optional `payload.snapshot.timing` object follows `display-timing.json`.
It carries snapshot commit time and available per-item source input traces.
The compact Mini projection omits this metadata.
Private `_source_timing` values carry provenance inside the provider and worker boundary.
The API moves those values into snapshot timing and omits them from renderer data.

Fastcast source traces can include `source_published_at_ms` from the nested publication wrapper's `ts` field.
`source_timestamp_kind: publisher_envelope` identifies that timestamp basis.
It does not establish the time of the real-world play.

`ingested_at_ms` uses the boundary named by `input_boundary`.
`fastcast_socket_received` marks the complete Fastcast socket receive, before wrapper decoding and patch application.
`http_snapshot_applied` marks an HTTP snapshot applied to the provider cache.
`core_worker_result_received` marks receipt of canonical data from a provider worker when no earlier trace exists.
`core_received_at_ms` and `request_started_ms` retain the core worker handoff and request boundaries when available.
Missing upstream times remain absent. They do not become invented live-event timestamps.

The Pi writes `kind: latency` records to its bounded performance log.
It measures only the first successful presentation of each source trace per item and device.
Scrolling updates require a current pane version with changed pixels inside the visible viewport.
Superseded updates and unchanged pixels do not produce a first-display latency.
The end boundary is frame-sink return. The physical matrix sink returns after its vertical-sync swap.
Clock-order failures remain explicit. Cross-host UTC differences require synchronized clocks.

Use `tools/diagnostics/latency_report.py --log capture.jsonl --output previews/latency/report.json` to summarize captured history.

## Message types

| Type | Fields | Meaning |
|---|---|---|
| `snapshot` | `payload` | Full effective display projection. |
| `delta` | `changes`, `removed` | Changed top-level projection fields and removed field names. |
| `ready` | None | The server accepted the client's current replay cursor. |

Snapshots use the same payload as `GET /data`.

A delta has `base_seq` equal to the client's current sequence. Its `seq` equals `base_seq + 1`.

## Replay and recovery

The server keeps 256 deltas per ticker. It sends replay when the stream ID and cursor match retained history.

The server sends a full snapshot when a stream ID changes, a cursor expires, or a client queue fills. The client drops duplicate sequence values.

The client drops its cursor after a gap or malformed delta. It reconnects without a cursor and receives a full snapshot.

The server bounds each client queue to 32 messages. Snapshot writes and HTTP mutations wake the projector for affected tickers.

The projector checks active tickers once per second for time-based schedule and event expiry changes.

The server sends WebSocket Ping frames every 20 seconds. The client library answers Ping frames with Pong frames. Hypercorn does not expose a Pong timeout setting.

HTTP heartbeat and command acknowledgement routes remain independent from stream traffic. The Mini keeps its HTTP poll path.
The device sends no messages. A device message closes the stream with code `1008`. `docs/api.md` lists the close codes.
