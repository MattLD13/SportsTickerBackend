# Sports Ticker Backend

Flask backend for LED sports ticker displays. It aggregates sports scores, golf leaderboards, stocks, weather, Spotify playback, and flight information, then serves ticker-specific display payloads to paired devices.

## What It Does

- Serves display data for one or many ticker devices.
- Stores global settings in `global_config.json` and per-device settings in `ticker_data/*.json`.
- Keeps background workers running for sports, stocks, music, and flights.
- Supports per-ticker modes, teams, timezone detection, pinned games, live delay, brightness/sleep behavior, and hardware reboot/update flags.
- Keeps `app.py` as a compatibility entrypoint while the implementation lives in the `sports_ticker` package.

## Current Architecture

```text
app.py                         Compatibility entrypoint
sports_ticker/runtime.py        App factory and server runner
sports_ticker/routes_runtime.py Flask app creation and route registration
sports_ticker/core.py           Shared state, constants, caches, helpers
sports_ticker/workers.py        Background refresh workers
sports_ticker/leagues.py        League, mode, stock, and golf metadata
sports_ticker/fetchers/         Sports, weather, stock, Spotify, flight fetchers
sports_ticker/routes/           API route modules
sports_ticker/services/         Compatibility helper exports
ticker_controller.py            Raspberry Pi LED matrix controller
ESPstreamer/                    ESP32 goal horn streaming tools
```

Recent cleanup centralized ticker creation, pairing helpers, mode normalization, shared route constants, and debug/test-mode syncing so route modules do less hand-rolled duplication.

## Supported Content

Sports and utilities are defined in `sports_ticker/leagues.py`.

- NFL
- MLB
- NHL
- NBA
- NCAA Football, FBS and FCS
- March Madness
- PGA Golf, including Masters/PGA Championship branding fallbacks
- Soccer: Premier League, FA Cup, Championship, World Cup, Champions League, Europa League, MLS
- Weather
- Clock
- Spotify now playing
- Flight tracker and airport activity
- Stock groups: Tech/AI, Momentum, Energy, Finance, Consumer

## Display Modes

Valid modes are:

```text
sports
sports_full
soccer_full
live
my_teams
stocks
weather
music
clock
golf
masters
flights
flight_tracker
```

Legacy modes are migrated automatically:

```text
all -> sports
flight2 -> flight_tracker
poop_fetcher -> sports
masters -> golf
```

Pinned sports games can temporarily display as `sports_full`; Masters pins can display as `masters` for compatibility.

## Setup

1. Install Python dependencies:

```powershell
pip install -r requirements.txt
```

2. Optional: create a `.env` file.

```env
PORT=5000
FLASK_SECRET_KEY=change-me

# Optional stock API keys. Without these, stocks run in simulation mode.
FINNHUB_KEY_1=your_key_here
FINNHUB_KEY_2=your_key_here
FINNHUB_KEY_3=your_key_here
FINNHUB_KEY_4=your_key_here
FINNHUB_KEY_5=your_key_here

# Optional Spotify support.
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REFRESH_TOKEN=your_refresh_token

# Optional flight and AI helpers.
FLIGHTAWARE_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
```

Optional Python packages unlock extra features when installed:

- `spotipy` for Spotify OAuth/client support
- `airportsdata` for airport lookup/autofill
- `FlightRadar24` SDK for flight tracking support
- `Pillow` for logo color extraction
- `google-genai` for Gemini-assisted airport/airline fallback lookups

3. Run the backend:

```powershell
python app.py
```

The server listens on `0.0.0.0:$PORT`, defaulting to `5000`.

## API Quick Reference

### Device Data

- `GET /data?id=<ticker_id>`  
  Returns the display payload for one ticker. Unknown IDs are auto-created and self-authorized with the ticker ID as the first client ID.

- `GET /api/state?id=<ticker_id>`  
  Returns current settings plus all current games/items with `is_shown` flags.

- `GET /api/teams`  
  Returns the fetched team catalog.

- `GET /api/my_teams?id=<ticker_id>`  
  Returns saved teams for a ticker.

### Pairing and Tickers

- `POST /register` with `X-Client-ID`  
  Creates a new paired ticker for the client, or returns the existing ticker for that client.

- `POST /pair` with `X-Client-ID` and JSON body `{"code": "123456", "name": "Kitchen"}`  
  Pairs a client to an existing ticker pairing code.

- `POST /pair/id` with `X-Client-ID` and JSON body `{"id": "<ticker_id>", "name": "Kitchen"}`  
  Pairs by ticker ID.

- `POST /ticker/<tid>/unpair` with `X-Client-ID`  
  Removes that client from the ticker.

- `GET /tickers` with `X-Client-ID`  
  Lists tickers associated with the client.

### Configuration

- `POST /api/config`  
  Updates global and/or ticker-scoped config. Use `ticker_id` in the JSON body or `?id=<ticker_id>` to target a ticker.

Common fields:

```json
{
  "ticker_id": "ticker-id",
  "mode": "sports",
  "active_sports": {"nhl": true, "nba": false},
  "my_teams": ["nhl:NJ", "mlb:NYY"],
  "weather_city": "New York",
  "weather_lat": 40.7128,
  "weather_lon": -74.006,
  "timezone_name": "America/New_York",
  "utc_offset": -4,
  "pinned_game": "nhl:123456"
}
```

- `POST /ticker/<tid>`  
  Updates a specific ticker's local settings. Requires `X-Client-ID` for an already paired client.

- `POST /api/pin_games`  
  Saves the active pin for a ticker. Body example: `{"ticker_id": "...", "game_ids": ["nhl:123456"]}`.

### Metadata and Utilities

- `GET /leagues`  
  Lists all available sports, utilities, and stock groups.

- `GET /api/spotify/now`  
  Returns cached Spotify playback state.

- `GET /api/blank-logo.png`  
  Returns the transparent placeholder logo.

- `GET /`  
  Basic health text.

### Flights

- `GET /api/airport/lookup?code=EWR`
- `GET /api/airports?q=newark`
- `GET /api/airlines`
- `GET /api/flight/status`
- `GET /api/flight/debug`

### Debug and Hardware

- `GET /api/timezone?id=<ticker_id>&refresh=1`
- `GET /timezone?id=<ticker_id>&refresh=1`
- `GET /api/debug`
- `POST /api/debug`
- `POST /api/hardware` with `{"action": "update"}` or `{"action": "reboot", "ticker_id": "..."}`
- `GET /errors`

## Storage and Caches

- `ticker_data/*.json`: per-ticker settings, clients, pairing code, teams, timezone, and flags.
- `global_config.json`: global active sports, default mode, weather, flight settings.
- `game_cache.json`: latest sports cache loaded at startup so displays are not blank after restart.
- `stock_cache.json`: stock cache.
- `airport_name_cache.json` and `airline_code_cache.json`: AI-assisted lookup caches.
- `ticker.log`: rolling server log mirrored from stdout/stderr.

## Background Workers

`sports_ticker/workers.py` starts:

- `sports_worker`: team catalog and sports buffer refreshes
- `stocks_worker`: stock sector/market updates
- `music_worker`: Spotify refreshes when music mode is needed
- `flights_worker`: airport and tracked visitor flight updates
- `refresh_worker`: coalesced central buffer rebuild queue

Workers start when `run_server()` is called. `create_app()` creates the Flask app without starting background workers, which is useful for tests and imports.

## Development

Compile/smoke-check the package:

```powershell
python -m compileall sports_ticker
```

Minimal Flask smoke test:

```powershell
@'
from sports_ticker import runtime
app = runtime.create_app()
client = app.test_client()
for path in ('/', '/leagues', '/api/state'):
    resp = client.get(path)
    print(path, resp.status_code)
'@ | python -
```

There is no full automated test suite yet. Be careful with changes to provider parsing in `sports_ticker/fetchers/`; ESPN, NHL, FotMob, MLB Stats API, and golf payloads differ in subtle ways.

## Deployment

`.github/workflows/deploy.yml` contains the deployment workflow. `app.py` remains the WSGI-compatible import target:

```python
from sports_ticker import create_app
app = create_app()
```

Running `python app.py` starts background workers and serves Flask.

## Data Sources

- ESPN site APIs for most sports and golf
- NHL native API for NHL live details
- FotMob for soccer detail fallbacks
- MLB Stats API for MLB challenge and live enrichment
- Finnhub for stocks, with simulation fallback
- Open-Meteo for weather and airport weather
- Spotify Web API for now playing
- FlightRadar24/FlightAware-related flight helpers where configured
- ip-api and Open-Meteo timezone fallback for ticker timezone detection

## Version

Current server version is defined in `sports_ticker/core.py` as:

```text
v0.10 - Optimized
```

## Notes

This project is personal/educational software. Keep generated runtime data, logs, caches, and `__pycache__` files out of commits unless you intentionally need a fixture.
