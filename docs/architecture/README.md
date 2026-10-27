# Architecture

Sports Ticker serves V2 content to Pi displays, ESP32 displays, the dashboard, and the iOS controller.

Read the [project map and cleanup plan](reviews/2026-10-27/project-map.md) for component boundaries, confirmed overlaps, deployment links, and the complete file inventory.

Read the [repository organization design](repository-layout.md) for current folder groups and stable entry points.

## Ownership

| Path | Responsibility |
|---|---|
| `ticker-server/sports_ticker/providers/sources/` | Read upstream data through injected source adapters. |
| `ticker-server/sports_ticker/providers/` | Read upstream sources and normalize provider content. |
| `ticker-server/sports_ticker/providers/sports_display.py` | Project shared sports display facts. |
| `ticker-server/sports_ticker/domain/` | Define immutable content, settings, schedules, and events. |
| `ticker-server/sports_ticker/application/` | Compose content, schedule refresh work, and retain snapshots. |
| `ticker-server/sports_ticker/fleet/repository.py` | Persist fleet settings, pairing, schedules, and integration state in SQLite. |
| `ticker-server/sports_ticker/projections/` | Produce JSON representations for API consumers. |
| `ticker-server/sports_ticker/api/routes.py` | Define V2 routes and request authorization. |
| `ticker-six/ticker_core/protocol/` | Poll the backend and validate V2 responses on the Pi. |
| `ticker-six/ticker_core/app/` | Build frames and manage the card viewport. |
| `ticker-six/ticker_core/features/` | Render content and overlays. |
| `ticker-six/ticker_core/platform/assets.py` | Store durable image cache files. |
| `ticker-six/ticker_core/assets/` | Plan assets and provide memory reads. |
| `ticker-mini/` | Build the ESP32 display firmware with PlatformIO. |
| `ticker-control/` | Build the iOS controller with Xcode. |

## Data flow

Independent provider workers feed the application scheduler. The scheduler composes ticker snapshots from content, fleet settings, and events.
The V2 projection exposes those snapshots to clients. Clients retain display state and render frames.
Rendering does not fetch provider data or define backend policy.

`SnapshotStore` retains current snapshots and bounded source-content history in memory.
Its default history window is 180 seconds. SQLite retains fleet state separately.
Snapshot revisions identify backend replacements. They do not define a replayable delta stream.

## Deployment

`ticker-server/sports_ticker/server.py` starts Hypercorn with one ASGI worker.
`ticker-server/sports_ticker/asgi.py` owns the production runtime through ASGI lifespan and adapts existing Flask HTTP routes with `WsgiToAsgi`.
`ticker-server/deploy/ticker.service` starts that backend entry point.
`ticker-controller.service` starts `python3 -m ticker_core` on the Pi.
`setup.sh` installs Pi releases as immutable Git worktrees under `/opt/sports-ticker`.
The Pi service stores runtime data under `/home/mld/ticker` outside each release.
`updater.py` manages release updates. Existing deployment workflows remain in `.github/workflows/`.

## Device stream status

The ASGI application serves Flask HTTP routes and owns one `BackendRuntime` lifecycle.
`TICKER_HTTP_THREADS` bounds concurrent Flask work through per-request thread-sensitive contexts.
`WS /api/v2/tickers/<ticker_id>/stream` sends effective projection snapshots and sequenced deltas.
The Pi reads an HTTP snapshot at boot, then resumes the stream with `stream_id` and `after_seq`.
Read [Device Stream V1](../contracts/device-stream-v1.md) for replay and recovery rules.
The service runs one worker until cross-worker snapshot publication has a design and validation.
The Pi controller service remains a separate process and release.

Read [the revised engineering SOW](../plans/engineering-sow.md) for stream ownership, rollout gates, and replay requirements.

## Contracts

Read [V2 contracts](../contracts/overview.md) for the current data envelope and source definitions.
Read [the agent guide](../../AGENTS.md) for domain ownership and change rules.

## Deployment ownership

`ticker-server/backend_ops/deployment/` owns component selection, immutable backend releases, and recovery.
`ticker-server/backend_ops/manager.py` retains the installed command entry point.
Other `ticker-server/backend_ops/` modules own workers, diagnostics, and reporting.
The core and ten provider workers have separate service processes and release identities.
`ticker-server/deploy/` stores their service units and the external recovery timer.
Read [backend recovery](../operations/backend-recovery.md) for activation, quarantine, and rollback rules.

The root `setup.sh`, `updater.py`, and `ticker-controller.service` remain public installation entry points for deployed Pi releases.
Their stable paths let installed tickers activate later releases.

## Repository layout

`tests/python/` contains the current Python suite.
`tests/native/` contains firmware contract and layout checks.
`tests/fixtures/` contains captured provider data and deterministic display inputs.
`tools/` groups rendering, Mini utilities, diagnostics, deployment, benchmarks, and experiments.
