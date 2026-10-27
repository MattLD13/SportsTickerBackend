# Sports Ticker

Sports Ticker serves live content to 384x32 Raspberry Pi LED matrices. The backend and Pi controller use only API V2.

Read [Architecture](docs/architecture/README.md), [Contributing](docs/development/README.md), [V2 contracts](docs/contracts/overview.md), the [revised SOW](docs/plans/engineering-sow.md), and its [feasibility review](docs/plans/feasibility.md).

## Architecture

```text
Provider workers -> per-ticker scheduler -> V2 snapshot -> ticker_core runtime -> frame sink -> 384x32 panel
                 |                       |
                 |                       +-> dashboard and controller app
                 +-> SQLite ticker settings, pairing, events, and integrations
```

`ticker-server/sports_ticker/` owns provider reads, per-ticker settings, snapshots, pairing, Spotify connections, events, and the Flask API.

`ticker-six/ticker_core/` owns V2 transport, content caching, runtime scheduling, rendering, and matrix drivers.

`ticker-control/` is the iOS controller app. It uses V2 controller credentials and never receives Spotify tokens.

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

## API V2

The Pi reads one endpoint:

```text
GET /api/v2/tickers/<ticker-id>/data
```

The response contains a ticker-specific snapshot, effective display settings, overlays, health, and pairing state. The backend projects domain facts once. Clients render those facts and do not infer team ownership from status text.

Useful endpoints:

| Method | Endpoint | Use |
|---|---|---|
| `GET` | `/api/v2/health` | Scheduler health. |
| `GET` | `/api/v2/tickers` | List provisioned tickers. |
| `POST` | `/api/v2/tickers` | Provision a ticker. |
| `PATCH` | `/api/v2/tickers/<ticker-id>` | Change ticker display settings. |
| `POST` | `/api/v2/tickers/<ticker-id>/heartbeat` | Report Pi health. |
| `POST` | `/api/v2/tickers/<ticker-id>/commands/reboot` | Request one paired ticker reboot. |
| `POST` | `/api/v2/pairings/exchange` | Claim a pairing code and receive a controller token. |
| `POST` | `/api/v2/tickers/<ticker-id>/integrations/spotify/authorizations` | Start Spotify authorization. |

Read [API V2 route definitions](ticker-server/sports_ticker/api/routes.py) for validation rules and complete route coverage.

## Development

Install the workspace packages before running tools:

```bash
python -m pip install -e . -r requirements-backend.txt
```

Start a product with its declared release paths:

```bash
python run.py server
python run.py six
```


Run the focused V2 suite:

```powershell
python -m pytest -q
```

Render a deterministic V2 snapshot without hardware:

```powershell
python tools\rendering\render_frame.py --snapshot tests\fixtures\display\v2_render_snapshot.json --mode sports --item-id nfl-live --no-prefetch --output previews\nfl.png
```

Run the local V2 API, Pi WebSocket client, and matrix bench through online, disconnected, and recovered states:

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
python tools\rendering\render_frame.py --url http://127.0.0.1:5000 --ticker-id <ticker-id> --mode sports --no-prefetch --output previews\live.png
```

If a display change alters pixels, render a 384x32 PNG before you commit it.

## Data ownership

Each fact has one owner. Providers normalize upstream data. `SportsDisplayProjector` assigns sports state such as `activeTeam`. The API projects canonical V2 data. The Pi and app consume that contract.

Do not add a legacy route, normalizer, fallback, or duplicate parser. Replace the incorrect boundary and delete its obsolete callers, tests, fixtures, and documentation.

## Repository map

| Folder | Owner |
|---|---|
| `ticker-server/` | Ticker Server code, backend operations, and service units. |
| `ticker-six/` | Ticker Six runtime and rendering. |
| `ticker-mini/` | Ticker Mini firmware. |
| `ticker-control/` | iOS controller app. |
| `ai/` | AI workspace tooling, tests, guides, and context configuration. |
| `tests/` | Python tests, native firmware checks, and fixtures. |
| `tools/` | Utilities grouped by purpose. |
| `docs/` | Architecture, contracts, development, operations, plans, and research. |

Read the [documentation index](docs/README.md) for current guides.
The build workflow has validation and publishing checks.
Publishing contains Ticker Server, Ticker Mini, and Ticker Six sections.
