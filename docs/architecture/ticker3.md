# Ticker 3 server

Ticker 3 is the server. It lives in `ticker3/`. `docs/api.md` lists every route.
The providers, the projections, and the fleet records stay in `sports_ticker/`.

## Parts

| Part | Folder | Job |
|---|---|---|
| API | `ticker3/api/` | The routes, request checks, authorization, and the device stream. |
| Web | `ticker3/web/` | The landing page, the dashboard, the panel demos, and the alert gallery. |
| Engine | `ticker3/core/engine.py` | Turns tickers and settings into subscriptions, and publishes snapshots through `RefreshService`. |
| Supervisor | `ticker3/core/supervisor.py` | Starts, watches, replaces, rolls back, and adopts worker processes. |
| Worker | `ticker3/worker/` | Hosts one provider. Owns its interval, batch reads, live passes, and failure pauses. |
| Contract | `ticker3/contract/` | The worker list, line framing, worker messages, and the result encoding. |
| Server | `ticker3/server.py` | Builds the application and serves it with Hypercorn. |
| Offline application | `ticker3/offline.py` | Builds the same routes without an engine, for tests and tools. |

## Processes

The core process serves the API and runs the engine. The core makes the clock result, because the clock has no upstream.
Each provider in `ticker3.contract.WORKERS` runs in its own worker process.
A worker loads only its provider, the domain model, the contract, and the incident store.
It loads no route, engine, projection, or Six code. `tests/python/operations/test_component_graph.py` checks this rule.

## Subscriptions

A subscription is one ticker, one provider, and the provider settings key of that ticker.
`sports_ticker/application/provider_keys.py` names the settings that can change each provider result.
A result goes only to the ticker and the settings key that asked for it.

Each pass, the engine:

1. resolves the settings of each registered ticker,
2. asks `ProviderDemand` which tickers need each provider,
3. sends each worker its full subscription set,
4. publishes each ticker that got a new result. The snapshot holds the result of each provider whose key matches the current settings.

A settings change gives a new key, so the worker reads the new subscription at once.
A result for an old key does not publish. If demand stops, the ticker keeps its last good data.
`tests/python/ticker3/test_engine.py` checks these rules.

## Worker rules

- An interval pass reads every subscription. The intervals are in `ticker3/worker/runner.py`.
- A provider with `fetch_batch_for_tickers` reads all its tickers in one call.
- A Fastcast version change starts a live pass for the tickers that follow the changed league.
- An unhealthy result is not sent, so the core keeps the last good data.
- After 3 failures, a ticker setting pauses for 30 seconds. The pause doubles up to 300 seconds. `ticker3/worker/recovery.py` owns this rule.
- The worker sends its job health, so `/health` shows each provider.

## Worker protocol

The core listens on one Unix socket. Each message is one JSON object on one line.

| Direction | Type | Content |
|---|---|---|
| worker to core | `hello` | Protocol version, provider, release, and process ID |
| core to worker | `welcome` | Acceptance, or the reason for refusal |
| core to worker | `subscribe` | The full set of subscriptions, as key to ticker and settings |
| worker to core | `result` | One healthy `ProviderResult` in the `ticker3/contract/results.py` encoding |
| worker to core | `health` | Errors, job health, paused circuits, memory, and busy time, every 5 seconds |
| core to worker | `drain` | A request to stop |

## Supervisor rules

- If a worker exits, sends no health for 20 seconds, or stays in one provider read for 45 seconds, it restarts with backoff.
- If a release crashes 3 times in 30 minutes, it is marked bad and the previous release becomes active.
- `POST /workers/<provider>/deploy` starts the new release next to the active one. The new release becomes active after it sends a result for every subscription. Then the old worker gets `drain`.
- If the new release fails, the old release stays active and the new release is marked bad.
- A release with a `.venv` folder runs on that dependency environment.
- If the core stops, the workers keep running. The next core adopts them. A worker that has no core for 10 minutes stops.

## Deployment

`backend_ops/` packages one release, moves the core to it, and asks the supervisor to move the selected workers.
Read [backend recovery](../operations/backend-recovery.md) for the release layout, the guard, and the first Ticker 3 deployment.

## Proof of the same output

`tests/fixtures/ticker3/golden_views.json` holds the full view and the device view of four tickers.
The old scheduler made them from replay providers that return real provider results recorded on 2026-10-29.
`tests/python/ticker3/test_engine_equivalence.py` runs the Ticker 3 server with the same providers, and the views must be equal.
Only `snapshot.revision`, `snapshot.timing`, and `snapshot.observed_at` can differ.
The Six ignores the same three fields when it decides whether the display changed.

`tools/diagnostics/virtual_hardware_lab.py` runs the real Six client against the real API over Hypercorn.
It registers, streams, loses the connection, resumes from its cursor, and draws 384x32 frames.

## Run

```bash
python -m ticker3.server
```

`ticker3/server.py` lists the settings.
