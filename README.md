# Sports Ticker

Sports Ticker serves live content to 384x32 Raspberry Pi LED matrices (Ticker Six), 64x32 ESP32 panels (Ticker Mini), and an iOS controller app.

Read [Architecture](docs/architecture/README.md), [the API](docs/api.md), [Contributing](docs/development/README.md), [display contracts](docs/contracts/overview.md), the [revised SOW](docs/plans/engineering-sow.md), and its [feasibility review](docs/plans/feasibility.md).

## Architecture

```text
Provider workers -> core engine -> ticker snapshot -> /data, /poll, /stream -> Six and Mini runtimes -> panels
      ^                 |                                   |
      |                 |                                   +-> dashboard and controller app
      +-- supervisor ---+-> SQLite ticker settings, pairing, events, and integrations
```

The repository has one folder for each product:

- `server/` is Ticker Server: the routes, the device stream, the engine, the worker supervisor, the provider workers, the records, and the server operations.
- `six/` is Ticker Six: transport, content caching, runtime scheduling, device services, and matrix drivers.
- `shared/` holds the code that the server and the Six both use: the content model, the leagues, the sports display facts, and the panel drawing code in `ticker.panel`.
- `mini/` is the Ticker Mini firmware. `ios/` is the iOS controller app. The app uses controller tokens and never receives Spotify tokens.

The Python code of `shared/`, `server/`, and `six/` forms one package, `ticker`. Each device gets only its folders. Run a product from the repository root:

```sh
PYTHONPATH=shared:server python -m ticker.server
PYTHONPATH=shared:six python -m ticker.six
```

## Modes

| Mode | Content |
|---|---|
| `sports` | Scores, golf, and racing. A pinned game uses the sports pinned presentation. |
| `stock` | Selected market groups. |
| `weather` | Current and forecast weather. |
| `music` | Connected Spotify playback. |
| `flights` | Visitor flight tracking. |
| `airports` | Airport arrivals and departures. |
| `clock` | Full-panel time and date. |
| `pairing` | Effective output only while a ticker is unpaired. |

Alerts, news, connection loss, and updates render as overlays. They do not replace the active mode.

## API

Paths have no version prefix. A device token names its ticker, so device paths have no ticker ID.

```text
GET  /data      Six display data
POST /poll      Mini telemetry and compact display data
WS   /stream    Live display data for the Six
```

The response contains a ticker-specific snapshot, effective display settings, overlays, health, and pairing state. The backend projects domain facts once. Clients render those facts and do not infer team ownership from status text.

Read [the API](docs/api.md) for every route, its authorization, and its error codes.

## Development

Run the test suite:

```powershell
python -m pytest -q
```

Render a deterministic snapshot without hardware:

```powershell
python tools\rendering\render_frame.py --snapshot tests\fixtures\display\render_snapshot.json --mode sports --item-id nfl-live --no-prefetch --output previews\nfl.png
```

Run the local API, Pi WebSocket client, and matrix bench through online, disconnected, and recovered states:

```powershell
python tools\diagnostics\virtual_hardware_lab.py
```

See the [virtual hardware lab guide](docs/development/hardware-lab.md) for its coverage and limits.

Compare pane scrolling composition strategies:

```powershell
python tools\benchmarks\pi_pane_composition.py
```

See [benchmark notes](tools/benchmarks/README.md) for measured results and limits.

Render from a running backend:

```powershell
python tools\rendering\render_frame.py --url http://127.0.0.1:5000 --device-token-file <token-file> --mode sports --no-prefetch --output previews\live.png
```

If a display change alters pixels, render a 384x32 PNG before you commit it.

## Data ownership

Each fact has one owner. Providers normalize upstream data. `SportsDisplayProjector` assigns sports state such as `activeTeam`. The API projects canonical display data. The Pi and app consume that contract.

Do not add a legacy route, normalizer, fallback, or duplicate parser. Replace the incorrect boundary and delete its obsolete callers, tests, fixtures, and documentation.

## Repository map

| Folder | Owner |
|---|---|
| `shared/` | The content model, the leagues, and the sports display facts (`ticker.shared`). Used by the server and the Six. |
| `server/` | Ticker Server (`ticker.server`), server operations (`ticker.ops`), and the server units in `deploy/`. |
| `six/` | Ticker Six (`ticker.six`), and its install script and unit in `deploy/`. |
| `mini/` | Ticker Mini firmware (PlatformIO). |
| `ios/` | iOS controller app (Xcode). |
| `agents/` | Agent workspace tools, their manifest, and their docs. The root `AGENTS.md` holds every agent rule. |
| `requirements/` | `base.txt` for the Six and the server, `server.txt` for the server. |
| `tests/` | Tests in folders that mirror the products: `shared/`, `server/`, `six/`, `ops/`, `agents/`, `mini/`, `tools/`, and `fixtures/`. |
| `tools/` | Utilities grouped by purpose. |
| `docs/` | Architecture, contracts, development, operations, plans, and research. |

Read the [documentation index](docs/README.md) for current guides.
The build workflow has validation and publishing checks.
Publishing contains Ticker Server, Ticker Mini, and Ticker Six sections.
