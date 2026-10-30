# Project map

This map shows where each part of the repository lives and which part owns each fact.

## Top level

The repository has one folder for each product, and folders for the work that crosses products.

```text
shared/            Facts that the server and the Six both use. No I/O.
  ticker/shared/   The Python package ticker.shared.
server/            Ticker Server.
  ticker/server/   The API, web pages, engine, workers, providers, projections, and records.
  ticker/ops/      Server deployment, recovery, and diagnostics.
  deploy/          The systemd units of the server.
six/               Ticker Six, the 384x32 Pi display.
  ticker/six/      The runtime, rendering, platform services, and the release updater.
  deploy/          The install script and the systemd unit of the Six.
mini/              Ticker Mini firmware for the 64x32 panel (PlatformIO).
ios/               The iOS controller app (Xcode) and its Swift package.
agents/            The agent workspace tools, their manifest, and their docs. AGENTS.md holds every agent rule.
requirements/      base.txt (the Six and the server) and server.txt (the server only).
tests/             Tests in folders that mirror the products.
tools/             Utilities grouped by purpose.
docs/              Architecture, API, contracts, development, operations, plans, and research.
```

## Python package `ticker`

`shared/`, `server/`, and `six/` each hold one part of the Python package `ticker`.
The folder `ticker/` in each product has no `__init__.py`, so Python merges the three parts into one namespace package.
The import names stay short: `ticker.shared`, `ticker.server`, `ticker.ops`, and `ticker.six`.
A Python package named `six` would hide the PyPI library `six`, which the server dependencies import.

Python finds the parts through `PYTHONPATH=shared:server:six`, relative to the repository or release folder.
`server/ticker/server/contract/__init__.py:SOURCE_ROOTS` names these roots for the deploy tools and the supervisor.
The server unit, the Six unit, CI, and pytest set the path. Each tool in `tools/` adds the roots itself.
A provider worker gets `shared/` and `server/` only, so it cannot load Six code.

The import direction is fixed:

- `ticker.shared` imports no other `ticker` package.
- `ticker.six` imports `ticker.shared` only.
- `ticker.server` imports `ticker.shared`, `ticker.ops`, and the Six renderer for the web demos.
- `ticker.ops` imports the standard library and `ticker.server.contract`. The guard timer runs it on the system Python.

| Folder | Owner |
|---|---|
| `shared/ticker/shared/domain/` | The content model, display settings, schedules, events, and snapshots. |
| `shared/ticker/shared/sports_display.py` | Sports display facts, such as the active team, situations, and racing names. |
| `shared/ticker/shared/leagues.py`, `immutable.py`, `payloads.py` | League data, immutable values, and payload helpers. |
| `shared/ticker/shared/images.py`, `music_palette.py`, `racing_session.py` | Image decoding, album colors, and racing session names. |
| `server/ticker/server/main.py` | The server entry point. `python -m ticker.server` runs it. |
| `server/ticker/server/api/` | The routes, request checks, authorization, and the device stream. |
| `server/ticker/server/web/` | The landing page, the dashboard, the panel demos, and the alert gallery. |
| `server/ticker/server/core/` | The engine and the worker supervisor. |
| `server/ticker/server/worker/` | The provider worker process. |
| `server/ticker/server/contract/` | The worker list and the messages between the core and the workers. |
| `server/ticker/server/providers/` | Provider reads and their normalization. |
| `server/ticker/server/services/` | Application services: refresh, schedules, events, and provider demand. |
| `server/ticker/server/projections/` | The device data and the data API projections. |
| `server/ticker/server/store/` | SQLite records: tickers, pairing, schedules, events, Spotify, and updates. |
| `server/ticker/server/mini_assets/` | Mini sprites and album artwork. |
| `server/ticker/server/spotify.py`, `firmware.py`, `markets.py`, `tls.py` | Spotify accounts, the Mini firmware manifest, market calendars, and TLS settings. |
| `six/ticker/six/protocol/` | The server client, the device stream, and response checks. |
| `six/ticker/six/app/` | The frame builder, the viewport, and the poller. |
| `six/ticker/six/runtime/` | Display state and pacing. |
| `six/ticker/six/ui/` | Cards, screens, and overlays. Rendering has no I/O. |
| `six/ticker/six/assets/` | Asset planning and memory reads. |
| `six/ticker/six/platform/` | Wi-Fi, Bluetooth setup, health, identity, and updates. |
| `six/ticker/six/drivers/` | The LED matrix and the emulator sinks. |
| `six/ticker/six/updater.py` | The release installer. `python3 -m ticker.six.updater` runs it from a release folder. |
| `six/ticker/six/diagnostics.py` | Hardware, Wi-Fi, and server checks. `python3 -m ticker.six.diagnostics` runs it. |
| `server/ticker/ops/manager.py` | Release activation, rollback, and the guard timer. |
| `server/ticker/ops/components.py` | The release package and the processes that a change reaches. |

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
| Server | `python -m ticker.server` in `server/deploy/ticker.service` | `ticker.ops.manager deploy` from the deploy workflow. It installs the units and the guard toolkit of each release. |
| Six | `python3 -m ticker.six` in `six/deploy/ticker-controller.service` | `six/deploy/setup.sh` for a new Pi. `ticker.six.updater` for each later release. |
| Mini | `mini/` firmware image | The deploy workflow publishes it. The server sends the over-the-air update. |
| iOS | `ios/TickerControl.xcodeproj` | Xcode. The iOS workflow builds it. |

`.github/deployment-paths.json` lists the paths that start each deployment.
