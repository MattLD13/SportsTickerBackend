# Ticker 3 engine

Ticker 3 replaces the refresh engine of the server. It lives in `ticker3/`.
Everything that decides how a ticker looks stays the same: the V2 routes, the projections,
the providers and `sports_display.py`, the Six renderer, the Mini firmware, and the iOS app.

## What changes

| Part | Old engine | Ticker 3 engine |
|---|---|---|
| Read timing | The core scheduler polls each worker at a fixed interval. | Each worker owns the timing of its provider and pushes each result. |
| ESPN live changes | The core long-polls the ESPN worker for Fastcast versions. | The ESPN worker watches Fastcast and starts a live pass itself. |
| Worker transport | One request and one answer per socket connection. | One connection per worker. Results and health flow without requests. |
| Worker lifecycle | systemd units, a guard timer, and the release manager. | The core supervisor restarts, replaces, and rolls back workers. |
| Clock | A worker process. | The core makes the clock result. The clock has no upstream. |
| Core restart | Workers keep running, but core polls start again. | Workers keep running and connect again. The core adopts them. |

## Parts

| Part | Folder | Job |
|---|---|---|
| Contract | `ticker3/contract/` | Line framing and the worker messages. |
| Worker | `ticker3/worker/` | Hosts one existing provider. Owns its interval, batch reads, live passes, and failure pauses. |
| Engine | `ticker3/core/engine.py` | Turns tickers and settings into subscriptions and publishes snapshots through `RefreshService`. |
| Supervisor | `ticker3/core/supervisor.py` | Starts, watches, replaces, rolls back, and adopts worker processes. |
| Server | `ticker3/server.py` | Builds the unchanged V2 application with the engine. |

## Subscriptions

A subscription is one ticker, one provider, and the provider settings key of that ticker.
`sports_ticker/application/provider_keys.py` names the settings that can change each provider result.
The old scheduler cached results with the same key, so a result goes only to the ticker that asked for it.

Each pass, the engine:

1. resolves the settings of each registered ticker,
2. asks `ProviderDemand` which tickers need each provider,
3. sends each worker its full subscription set,
4. publishes each ticker that got a new result. The snapshot holds the result of each provider whose key matches the current settings.

A settings change gives a new key, so the worker reads the new subscription at once.

## Worker rules

These rules match the old core scheduler:

- An interval pass reads every subscription. The intervals are in `ticker3/worker/runner.py`.
- A provider with `fetch_batch_for_tickers` reads all its tickers in one call.
- A Fastcast version change starts a live pass for the tickers that follow the changed league.
- An unhealthy result is not sent, so the core keeps the last good data.
- After 3 failures, a ticker setting pauses for 30 seconds. The pause doubles up to 300 seconds.
- The worker sends its job health, so `/api/v2/health` keeps its fields.

## Worker protocol

The core listens on one Unix socket. Each message is one JSON object on one line.

| Direction | Type | Content |
|---|---|---|
| worker to core | `hello` | Protocol version, provider, release, and process ID |
| core to worker | `welcome` | Acceptance, or the reason for refusal |
| core to worker | `subscribe` | The full set of subscriptions, as key to ticker and settings |
| worker to core | `result` | One healthy `ProviderResult` in the `backend_ops.worker_contract` encoding |
| worker to core | `health` | Errors, job health, paused circuits, memory, and busy time, every 5 seconds |
| core to worker | `drain` | A request to stop |

## Supervisor rules

- If a worker exits, sends no health for 20 seconds, or stays in one provider read for 45 seconds, it restarts with backoff.
- If a release crashes 3 times in 30 minutes, it is marked bad and the previous release becomes active.
- A deploy starts the new release next to the active one. The new release becomes active after it sends a result for every subscription. Then the old worker gets `drain`.
- If the new release fails, the old release stays active and the new release is marked bad.
- A worker that has no core for 10 minutes stops.

## Proof of the same output

`tests/python/ticker3/test_engine_equivalence.py` runs the old production composition and the Ticker 3 server
with the same replay providers. The replay providers return real provider results recorded on 2026-10-29.
For each ticker, the full view and the device view of `project_data` must be equal.
Only `snapshot.revision`, `snapshot.timing`, and `snapshot.observed_at` can differ.
The Six ignores the same three fields when it decides whether the display changed.

A live run on 2026-10-29 read the real upstreams with both engines at the same time.
The V2 payloads of a sports, a weather, and an airport ticker were equal, and the Six renderer drew them.

## Run

```bash
python -m ticker3.server
```

`ticker3/server.py` lists the Ticker 3 settings. Every other setting keeps its meaning from `sports_ticker/production.py`.

## Not done yet

- The deployment workflow and `backend_ops/manager.py` still deploy the old engine.
  The old engine stays until the Ticker 3 supervisor takes over deployment.
