# Architecture

Sports Ticker serves display content to Pi displays, ESP32 displays, the dashboard, and the iOS controller.

Read the [project map and cleanup plan](project-map.md) for component boundaries, confirmed overlaps, deployment links, and the complete file inventory.

## Ownership

| Path | Responsibility |
|---|---|
| `sports_ticker/providers/` | Read upstream sources and normalize provider content. |
| `sports_ticker/providers/sports_display.py` | Project shared sports display facts. |
| `sports_ticker/domain/` | Define immutable content, settings, schedules, and events. |
| `sports_ticker/application/` | Compose content, apply schedules, and retain snapshots. |
| `sports_ticker/fleet/repository.py` | Persist fleet settings, pairing, schedules, and integration state in SQLite. |
| `sports_ticker/projections/` | Produce JSON representations for API consumers. |
| `ticker3/api/` | Define the routes, request checks, authorization, and the device stream. |
| `ticker3/core/` | Turn tickers into worker subscriptions, publish snapshots, and supervise worker processes. |
| `ticker3/worker/` | Run one provider in one process and send its results to the core. |
| `ticker_core/protocol/` | Read the backend and validate display responses on the Pi. |
| `ticker_core/app/` | Build frames and manage the card viewport. |
| `ticker_core/ui/` | Draw content cards, screens, and overlays. |
| `ticker_core/platform/assets.py` | Store durable image cache files. |
| `ticker_core/assets/` | Plan assets and provide memory reads. |
| `esp32_hub75/` | Build the ESP32 display firmware with PlatformIO. |
| `TickerControlApp/` | Build the iOS controller with Xcode. |

## Data flow

Each provider worker reads its upstream on its own interval and sends each new result to the core engine.
The engine composes ticker snapshots from those results, fleet settings, and events.
The projection exposes those snapshots to clients. Clients retain display state and render frames.
Rendering does not fetch provider data or define backend policy.

`SnapshotStore` retains current snapshots and bounded source-content history in memory.
Its default history window is 180 seconds. SQLite retains fleet state separately.
Snapshot revisions identify backend replacements. They do not define a replayable delta stream.

## Deployment

`ticker3/server.py` starts Hypercorn with one ASGI process.
`ticker3/api/asgi.py` starts the engine through the ASGI lifespan and adapts the Flask routes with `WsgiToAsgi`.
`deploy/backend/ticker.service` starts that entry point. The engine supervisor starts the provider workers.
`ticker-controller.service` starts `python3 -m ticker_core` on the Pi.
`setup.sh` installs Pi releases as immutable Git worktrees under `/opt/sports-ticker`.
The Pi service stores runtime data under `/home/mld/ticker` outside each release.
`updater.py` manages release updates. Existing deployment workflows remain in `.github/workflows/`.

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

`backend_ops/` owns process selection, immutable backend releases, core recovery, and encrypted evidence collection.
The core and nine provider workers are separate processes. Each process has its own release identity.
The core supervisor restarts, deploys, and rolls back the workers. `deploy/backend/` stores the core unit and the guard timer.
Read [backend recovery](../operations/backend-recovery.md) for activation, quarantine, and rollback rules.

The root `setup.sh`, `updater.py`, and `ticker-controller.service` remain public installation entry points for deployed Pi releases.
Their stable paths let installed tickers activate later releases.

## Repository layout

`tests/python/` contains the current Python suite.
`tests/native/` contains firmware contract and layout checks.
`tests/fixtures/` contains captured provider data and deterministic display inputs.
`tools/` groups rendering, Mini utilities, diagnostics, deployment, benchmarks, and experiments.
