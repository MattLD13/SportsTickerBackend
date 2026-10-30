# Architecture

Sports Ticker serves display content to Pi displays, ESP32 displays, the dashboard, and the iOS controller.

Read the [project map](project-map.md) for the folder layout, the import direction, and the deployment links.

## Ownership

| Path | Responsibility |
|---|---|
| `ticker/server/providers/` | Read upstream sources and normalize provider content. |
| `ticker/shared/sports_display.py` | Project shared sports display facts. |
| `ticker/shared/domain/` | Define immutable content, settings, schedules, and events. |
| `ticker/server/services/` | Compose content, apply schedules, and retain snapshots. |
| `ticker/server/store/repository.py` | Persist fleet settings, pairing, schedules, and integration state in SQLite. |
| `ticker/server/projections/` | Produce JSON representations for API consumers. |
| `ticker/server/api/` | Define the routes, request checks, authorization, and the device stream. |
| `ticker/server/core/` | Turn tickers into worker subscriptions, publish snapshots, and supervise worker processes. |
| `ticker/server/worker/` | Run one provider in one process and send its results to the core. |
| `ticker/six/protocol/` | Read the backend and validate display responses on the Pi. |
| `ticker/six/app/` | Build frames and manage the card viewport. |
| `ticker/six/ui/` | Draw content cards, screens, and overlays. |
| `ticker/six/platform/assets.py` | Store durable image cache files. |
| `ticker/six/assets/` | Plan assets and provide memory reads. |
| `mini/` | Build the ESP32 display firmware with PlatformIO. |
| `ios/` | Build the iOS controller with Xcode. |

## Data flow

Each provider worker reads its upstream on its own interval and sends each new result to the core engine.
The engine composes ticker snapshots from those results, fleet settings, and events.
The projection exposes those snapshots to clients. Clients retain display state and render frames.
Rendering does not fetch provider data or define backend policy.

`SnapshotStore` retains current snapshots and bounded source-content history in memory.
Its default history window is 180 seconds. SQLite retains fleet state separately.
Snapshot revisions identify backend replacements. They do not define a replayable delta stream.

## Deployment

`ticker/server/main.py` starts Hypercorn with one ASGI process.
`ticker/server/api/asgi.py` starts the engine through the ASGI lifespan and adapts the Flask routes with `WsgiToAsgi`.
`deploy/server/ticker.service` starts that entry point. The engine supervisor starts the provider workers.
`deploy/six/ticker-controller.service` starts `python3 -m ticker.six` on the Pi.
`deploy/six/setup.sh` installs Pi releases as immutable Git worktrees under `/opt/sports-ticker`.
The Pi service stores runtime data under `/home/mld/ticker` outside each release.
`python3 -m ticker.six.updater` installs later releases. The deployment workflows are in `.github/workflows/`.

## Device stream status

The ASGI application serves the Flask routes and owns one engine lifecycle.
`TICKER_HTTP_THREADS` bounds concurrent Flask work through per-request thread-sensitive contexts.
`WS /stream` sends effective projection snapshots and sequenced deltas. The device token names the ticker.
The Pi reads an HTTP snapshot at boot, then resumes the stream with `stream_id` and `after_seq`.
Read [the device stream contract](../contracts/device-stream.md) for replay and recovery rules.
The service runs one worker until cross-worker snapshot publication has a design and validation.
The Pi controller service remains a separate process and release.

Read [the revised engineering SOW](../plans/engineering-sow.md) for stream ownership, rollout gates, and replay requirements.

## Contracts

Read [the API](../api.md) for every route.
Read [display contracts](../contracts/overview.md) for the current data envelope and source definitions.
Read [the agent guide](../../AGENTS.md) for domain ownership and change rules.

## Deployment ownership

`ticker/ops/` owns process selection, immutable backend releases, core recovery, and encrypted evidence collection.
The core and nine provider workers are separate processes. Each process has its own release identity.
The core supervisor restarts, deploys, and rolls back the workers. `deploy/server/` stores the core unit and the guard timer.
Read [backend recovery](../operations/backend-recovery.md) for activation, quarantine, and rollback rules.

`deploy/six/setup.sh` installs a new Pi. `ticker.six.updater` installs each later release and copies `deploy/six/ticker-controller.service` from that release.
Keep these paths stable, because an installed Six reads them from each new release.

## Repository layout

`tests/shared/`, `tests/server/`, `tests/six/`, `tests/ops/`, and `tests/tools/` contain the Python tests. They mirror the code.
`tests/mini/` contains the native firmware checks.
`tests/fixtures/` contains captured provider data and deterministic display inputs.
`tools/` groups rendering, Mini utilities, diagnostics, deployment, benchmarks, and experiments.
