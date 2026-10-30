# Project map

This map shows where each part of the repository lives and which part owns each fact.

## Top level

```text
ticker/            The Python code. One package. Run a product with `python -m ticker.<product>`.
  shared/          Facts that the server and the Six both use. No I/O.
  server/          Ticker Server.
  six/             Ticker Six.
  ops/             Server deployment, recovery, and diagnostics.
agents/            The agent workspace tools, their manifest, and their docs. AGENTS.md at the root holds every agent rule.
mini/              Ticker Mini firmware (PlatformIO).
ios/               iOS controller app (Xcode) and its Swift package.
deploy/server/     The systemd units of the server.
deploy/six/        The install script and the systemd unit of the Six.
requirements/      base.txt (the Six and the server) and server.txt (the server only).
tests/             Tests in folders that mirror the code.
tools/             Utilities grouped by purpose.
docs/              Architecture, API, contracts, development, operations, plans, and research.
```

## Python package `ticker`

The import direction is fixed:

- `ticker.shared` imports no other `ticker` package.
- `ticker.six` imports `ticker.shared` only.
- `ticker.server` imports `ticker.shared`, `ticker.ops`, and the Six renderer for the web demos.
- `ticker.ops` imports the standard library and `ticker.server.contract`. The guard timer runs it on the system Python.

| Folder | Owner |
|---|---|
| `ticker/shared/domain/` | The content model, display settings, schedules, events, and snapshots. |
| `ticker/shared/sports_display.py` | Sports display facts, such as the active team, situations, and racing names. |
| `ticker/shared/leagues.py`, `immutable.py`, `payloads.py` | League data, immutable values, and payload helpers. |
| `ticker/shared/images.py`, `music_palette.py`, `racing_session.py` | Image decoding, album colors, and racing session names. |
| `ticker/server/main.py` | The server entry point. `python -m ticker.server` runs it. |
| `ticker/server/api/` | The routes, request checks, authorization, and the device stream. |
| `ticker/server/web/` | The landing page, the dashboard, the panel demos, and the alert gallery. |
| `ticker/server/core/` | The engine and the worker supervisor. |
| `ticker/server/worker/` | The provider worker process. |
| `ticker/server/contract/` | The worker list and the messages between the core and the workers. |
| `ticker/server/providers/` | Provider reads and their normalization. |
| `ticker/server/services/` | Application services: refresh, schedules, events, and provider demand. |
| `ticker/server/projections/` | The device data and the data API projections. |
| `ticker/server/store/` | SQLite records: tickers, pairing, schedules, events, Spotify, and updates. |
| `ticker/server/mini_assets/` | Mini sprites and album artwork. |
| `ticker/server/spotify.py`, `firmware.py`, `markets.py`, `tls.py` | Spotify accounts, the Mini firmware manifest, market calendars, and TLS settings. |
| `ticker/six/protocol/` | The server client, the device stream, and response checks. |
| `ticker/six/app/` | The frame builder, the viewport, and the poller. |
| `ticker/six/runtime/` | Display state and pacing. |
| `ticker/six/ui/` | Cards, screens, and overlays. Rendering has no I/O. |
| `ticker/six/assets/` | Asset planning and memory reads. |
| `ticker/six/platform/` | Wi-Fi, Bluetooth setup, health, identity, and updates. |
| `ticker/six/drivers/` | The LED matrix and the emulator sinks. |
| `ticker/six/updater.py` | The release installer. `python3 -m ticker.six.updater` runs it from a release folder. |
| `ticker/six/diagnostics.py` | Hardware, Wi-Fi, and server checks. `python3 -m ticker.six.diagnostics` runs it. |
| `ticker/ops/manager.py` | Release activation, rollback, and the guard timer. |
| `ticker/ops/components.py` | The release package and the processes that a change reaches. |

## Tests

The folders under `tests/` mirror the code. A test lives in the folder of the code that it checks.

| Folder | Checks |
|---|---|
| `tests/shared/` | The content model and the sports display facts. |
| `tests/server/` | API, web, core, worker, providers, services, projections, store, and Spotify. |
| `tests/six/` | App, assets, UI and golden frames, platform, protocol, and runtime. |
| `tests/ops/` | Deployment and recovery. |
| `tests/mini/` | Native C++ checks of the Mini firmware. CI compiles them with `g++`. |
| `tests/agents/` | The agent workspace tools. |
| `tests/tools/` | Benchmark, deployment, diagnostic, Mini, and rendering tools. |
| `tests/fixtures/` | Recorded inputs and golden digests. |

## Deployment links

| Product | Entry | Installs |
|---|---|---|
| Server | `python -m ticker.server` in `deploy/server/ticker.service` | `ticker.ops.manager deploy` from the deploy workflow. It installs the units and the guard toolkit of each release. |
| Six | `python3 -m ticker.six` in `deploy/six/ticker-controller.service` | `deploy/six/setup.sh` for a new Pi. `ticker.six.updater` for each later release. |
| Mini | `mini/` firmware image | The deploy workflow publishes it. The server sends the over-the-air update. |
| iOS | `ios/TickerControl.xcodeproj` | Xcode. The iOS workflow builds it. |

`.github/deployment-paths.json` lists the paths that start each deployment.
