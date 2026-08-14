# Sports Ticker

Sports Ticker serves live content to 384x32 Raspberry Pi LED matrices. The backend and Pi controller use only API V2.

## Architecture

```text
Providers -> per-ticker scheduler -> V2 snapshot -> ticker_core runtime -> frame sink -> 384x32 panel
                 |                       |
                 |                       +-> dashboard and controller app
                 +-> SQLite ticker settings, pairing, events, and integrations
```

`sports_ticker/` owns provider reads, per-ticker settings, snapshots, pairing, Spotify connections, events, and the Flask API.

`ticker_core/` owns V2 transport, content caching, runtime scheduling, rendering, and matrix drivers.

`TickerControlApp/` is the iOS controller app. It uses V2 controller credentials and never receives Spotify tokens.

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
| `POST` | `/api/v2/pairings/exchange` | Claim a pairing code and receive a controller token. |
| `POST` | `/api/v2/tickers/<ticker-id>/integrations/spotify/authorizations` | Start Spotify authorization. |

Read [API V2 route definitions](sports_ticker/api/routes.py) for validation rules and complete route coverage.

## Development

Run the focused V2 suite:

```powershell
python -m pytest -q
```

Render a deterministic V2 snapshot without hardware:

```powershell
python tools\render_rewrite.py --snapshot tests\rewrite\debug\v2_render_snapshot.json --mode sports --item-id nfl-live --no-prefetch --output previews\nfl.png
```

Render from a running backend:

```powershell
python tools\render_rewrite.py --url http://127.0.0.1:5000 --ticker-id <ticker-id> --mode sports --no-prefetch --output previews\live.png
```

If a display change alters pixels, render a 384x32 PNG before you commit it.

## Data ownership

Each fact has one owner. Providers normalize upstream data. `SportsDisplayProjector` assigns sports state such as `activeTeam`. The API projects canonical V2 data. The Pi and app consume that contract.

Do not add a legacy route, normalizer, fallback, or duplicate parser. Replace the incorrect boundary and delete its obsolete callers, tests, fixtures, and documentation.
