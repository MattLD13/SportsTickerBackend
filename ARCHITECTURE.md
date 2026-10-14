# Architecture

Sports Ticker serves V2 content to Pi displays, ESP32 displays, the dashboard, and the iOS controller.

## Ownership

| Path | Responsibility |
|---|---|
| `sports_ticker/providers/` | Read upstream sources and normalize provider content. |
| `sports_ticker/providers/sports_display.py` | Project shared sports display facts. |
| `sports_ticker/domain/` | Define immutable content, settings, schedules, and events. |
| `sports_ticker/application/` | Compose content, schedule refresh work, and retain snapshots. |
| `sports_ticker/fleet/repository.py` | Persist fleet settings, pairing, schedules, and integration state in SQLite. |
| `sports_ticker/projections/` | Produce JSON representations for API consumers. |
| `sports_ticker/api/routes.py` | Define V2 routes and request authorization. |
| `ticker_core/protocol/` | Poll the backend and validate V2 responses on the Pi. |
| `ticker_core/app/` | Build frames and manage the card viewport. |
| `ticker_core/features/` | Render content and overlays. |
| `ticker_core/platform/assets.py` | Store durable image cache files. |
| `ticker_core/assets/` | Plan assets and provide memory reads. |
| `esp32_hub75/` | Build the ESP32 display firmware with PlatformIO. |
| `TickerControlApp/` | Build the iOS controller with Xcode. |

## Data flow

Providers feed the application scheduler. The scheduler composes ticker snapshots from content, fleet settings, and events.
The V2 projection exposes those snapshots to clients. Clients retain display state and render frames.
Rendering does not fetch provider data or define backend policy.

`SnapshotStore` retains current snapshots and bounded source-content history in memory.
Its default history window is 180 seconds. SQLite retains fleet state separately.
Snapshot revisions identify backend replacements. They do not define a replayable delta stream.

## Deployment

`sports_ticker/server.py` starts Hypercorn with one ASGI worker.
`sports_ticker/asgi.py` owns the production runtime through ASGI lifespan and adapts existing Flask HTTP routes with `WsgiToAsgi`.
`ticker.service` starts that backend entry point.
`ticker-controller.service` starts `python3 -m ticker_core` on the Pi.
`setup.sh` installs Pi releases as immutable Git worktrees under `/opt/sports-ticker`.
The Pi service stores runtime data under `/home/mld/ticker` outside each release.
`updater.py` manages release updates. Existing deployment workflows remain in `.github/workflows/`.

## Device stream status

The current ASGI application serves existing Flask HTTP routes and owns one `BackendRuntime` lifecycle.
`TICKER_HTTP_THREADS` bounds concurrent Flask work through per-request thread-sensitive contexts.
The WebSocket scope remains closed until Gate 2 defines and implements the device stream.
The service runs one worker until cross-worker snapshot publication has a design and validation.
The Pi controller service remains a separate process and release.

Read [the revised engineering SOW](docs/master-engineering-sow.md) for stream ownership, rollout gates, and replay requirements.

## Contracts

Read [V2 contracts](docs/v2-contracts.md) for the current data envelope and source definitions.
Read [the agent guide](AGENTS.md) for domain ownership and change rules.
