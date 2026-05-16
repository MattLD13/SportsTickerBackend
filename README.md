```
 ███████╗██████╗  ██████╗ ██████╗ ████████╗███████╗    ████████╗██╗ ██████╗██╗  ██╗███████╗██████╗
 ██╔════╝██╔══██╗██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝    ╚══██╔══╝██║██╔════╝██║ ██╔╝██╔════╝██╔══██╗
 ███████╗██████╔╝██║   ██║██████╔╝   ██║   ███████╗       ██║   ██║██║     █████╔╝ █████╗  ██████╔╝
 ╚════██║██╔═══╝ ██║   ██║██╔══██╗   ██║   ╚════██║       ██║   ██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗
 ███████║██║     ╚██████╔╝██║  ██║   ██║   ███████║       ██║   ██║╚██████╗██║  ██╗███████╗██║  ██║
 ╚══════╝╚═╝      ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝       ╚═╝   ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
```

> **384×32 LED matrix sports ticker** — scores, stocks, weather, flights, music, and more.  
> Flask backend · Raspberry Pi controller · OTA updates · multi-ticker fleet support

[![Deploy](https://github.com/MattLD13/SportsTickerBackend/actions/workflows/deploy.yml/badge.svg)](https://github.com/MattLD13/SportsTickerBackend/actions/workflows/deploy.yml)
&nbsp;·&nbsp; Live at [ticker.mattdicks.org](https://ticker.mattdicks.org)

---

## What it is

A custom sports ticker built on 6× chained 64×32 HUB75 RGB LED panels (384×32 total). A Flask server runs on an Ubuntu VPS, aggregates live data from a dozen sources, and serves display payloads to one or more Raspberry Pi controllers over the network. Each Pi drives the LED matrix directly.

```
 GitHub Push
      │
      ▼
 GitHub Actions ──► Ubuntu VPS (Flask backend)
                         │  /data polling every 5s
                         ▼
                   Raspberry Pi 4
                         │
                         ▼
              ⬛⬛⬛⬛⬛⬛  384×32 LED Matrix
```

---

## Hardware

| Component | Spec |
|-----------|------|
| Controller | Raspberry Pi 4 |
| Panels | 6× 64×32 HUB75 RGB LED |
| Interface | Adafruit RGB Matrix Bonnet |
| Total resolution | 384×32 pixels |
| Power | Separate 5V supply for panels |

---

## What it shows

| Category | Content |
|----------|---------|
| 🏈 Football | NFL · NCAA FBS · NCAA FCS |
| ⚾ Baseball | MLB |
| 🏒 Hockey | NHL |
| 🏀 Basketball | NBA · March Madness |
| ⚽ Soccer | Premier League · FA Cup · Championship · Champions League · Europa League · World Cup · MLS |
| ⛳ Golf | PGA Tour · Masters · PGA Championship |
| ✈️ Flights | Live flight tracker · Airport arrivals/departures |
| 📈 Stocks | Tech/AI · Momentum · Energy · Finance · Consumer |
| 🌤 Weather | Current conditions · AQI |
| 🎵 Music | Spotify now playing with album art colors |
| 🕐 Clock | Full-screen digital clock |

---

## Display Modes

```
sports          All active sports rotating
sports_full     Full-bleed scoreboard for a pinned game
soccer_full     Full-bleed soccer scoreboard
live            Only show games currently in progress
my_teams        Only show your saved teams
golf            PGA leaderboard scroll
masters         Masters/major championship branding
stocks          Stock ticker scroll
weather         Detailed weather card
music           Spotify now playing
clock           Full-screen clock
flights         Airport arrivals/departures board
flight_tracker  Single tracked flight (guest/visitor mode)
```

---

## Architecture

```
SportsTickerBackend/
├── app.py                          WSGI entrypoint
├── sports_ticker/                  Flask backend package
│   ├── core.py                     Shared state, constants, helpers, version
│   ├── workers.py                  Background refresh workers
│   ├── fetchers/                   Data fetchers
│   │   ├── sports.py               ESPN / NHL / MLB / golf
│   │   ├── weather.py              Open-Meteo
│   │   ├── stocks.py               Finnhub
│   │   ├── spotify.py              Spotify Web API
│   │   └── flights.py              FlightRadar24 SDK
│   └── routes/                     Flask route modules
│       ├── state.py                /data  /api/state
│       ├── config.py               /api/config
│       ├── ticker.py               /register  /pair  /tickers
│       ├── metadata.py             /  /leagues  /api/spotify/now
│       ├── flight.py               /api/airport/*  /api/flight/*
│       └── debug.py                /api/debug  /api/hardware  /errors
├── ticker_controller/              Raspberry Pi LED controller package
│   ├── controller.py               TickerStreamer — main render loop
│   ├── modes/                      Draw method mixins
│   │   ├── sports.py               Scoreboard layouts
│   │   ├── weather.py              Weather pixel art
│   │   ├── golf.py                 Golf leaderboard
│   │   ├── music.py                Vinyl/visualizer
│   │   ├── flight.py               Flight map/airport board
│   │   └── misc.py                 Clock, update screen
│   ├── fonts.py                    Tiny bitmap fonts + draw helpers
│   ├── stadium.py                  Stadium/logo renderer
│   ├── matrix.py                   RGBMatrix wrapper + NullMatrix fallback
│   └── config.py                   Panel dimensions, backend URL, constants
├── updater.py                      OTA updater — git pull + service restart
├── ticker-controller.service       systemd service file
├── setup.sh                        One-shot Pi setup script
└── .github/workflows/deploy.yml    Smart deploy: backend + controller separately
```

---

## Version Numbering

Version is derived automatically from git at server startup — **no manual bumping needed**.

```
2026.05.15 · build r312+abc1234d
│           │      │   └── short commit hash
│           │      └── total commit count (increments every push)
│           └── "build"
└── date of last commit
```

The current version is always visible at [ticker.mattdicks.org](https://ticker.mattdicks.org) and returned in every `/data` response as `"version"`.

---

## OTA Updates

Push to `main` → GitHub Actions detects what changed → updates only what's needed.

```
Backend changed  →  SCP to server  →  pip install  →  systemctl restart ticker
Controller changed  →  POST /api/hardware  →  Pi sees update flag  →  git pull  →  restart
```

- Backend and controller update **independently** — a controller push never touches the server
- The update screen on the LED matrix shows the incoming build number (`→ r315+abc1234`)
- `updater.py` auto-adds the git safe.directory so root can pull from a user-owned directory

---

## Pi Setup

```bash
# One-shot setup on a fresh Pi
sudo bash -c "curl -fsSL https://raw.githubusercontent.com/MattLD13/SportsTickerBackend/main/setup.sh | bash"
```

The script handles: apt packages · git clone · pip install · rgbmatrix build · sudoers · systemd.

After setup: `journalctl -u ticker-controller -f`

---

## Backend Setup

```bash
pip install -r requirements.txt
python app.py   # or: gunicorn app:app
```

`.env` file for secrets:

```env
FINNHUB_KEY_1=...          # Stock data (5 keys for rate limit rotation)
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REFRESH_TOKEN=...
GEMINI_API_KEY=...          # AI fallback for airport/airline lookups
```

Optional packages that unlock features when installed:

```
spotipy          Spotify OAuth
airportsdata     Airport code validation
FlightRadar24    Live flight tracking
google-genai     Gemini AI fallback lookups
```

---

## API Reference

### Core

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/data?id=<tid>` | Display payload for a ticker. Unknown IDs are auto-created. |
| `GET` | `/api/state?id=<tid>` | Full settings + all games with `is_shown` flags |
| `GET` | `/leagues` | All available sports, utilities, stock groups |
| `GET` | `/` | Status page — version, uptime, paired tickers, active sports |

### Pairing

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/register` | Create or fetch ticker for `X-Client-ID` |
| `POST` | `/pair` | Pair client to ticker by 6-digit code |
| `POST` | `/pair/id` | Pair by ticker ID |
| `POST` | `/ticker/<tid>/unpair` | Remove client from ticker |
| `GET` | `/tickers` | List tickers for client |

### Config

`POST /api/config` — update global or per-ticker settings:

```json
{
  "ticker_id": "ABCD1",
  "mode": "sports",
  "active_sports": { "nhl": true, "nba": false },
  "my_teams": ["nhl:NJ", "mlb:NYY"],
  "weather_city": "New York",
  "pinned_game": "nhl:123456"
}
```

### Flights

```
GET  /api/airport/lookup?code=EWR
GET  /api/airports?q=newark
GET  /api/airlines
GET  /api/flight/status
GET  /api/flight/debug
```

### Hardware & Debug

```
POST /api/hardware   {"action":"update"}                    — OTA update all tickers
POST /api/hardware   {"action":"reboot","ticker_id":"..."}  — reboot a ticker
GET  /api/debug
GET  /api/timezone?id=<tid>&refresh=1
GET  /errors
```

---

## Data Sources

| Source | Used for |
|--------|---------|
| ESPN (site API) | NFL, NBA, MLB, NCAA, golf |
| NHL native API | NHL live details |
| FotMob | Soccer detail fallback |
| MLB Stats API | Live pitch data, challenge flags |
| Finnhub | Stocks (simulates if no key) |
| Open-Meteo | Weather, AQI, timezone |
| Spotify Web API | Now playing |
| FlightRadar24 SDK | Live flight tracking |
| ip-api | Ticker timezone detection |
| Google Gemini | Airport/airline code AI fallback |

---

## Storage

| File | Contents |
|------|---------|
| `global_config.json` | Global active sports, mode, weather, flight settings |
| `ticker_data/*.json` | Per-ticker settings, clients, pairing, teams, timezone |
| `game_cache.json` | Sports cache — avoids blank display on restart |
| `stock_cache.json` | Stock cache |
| `ticker.log` | Rolling log (stdout/stderr mirror, `[DEBUG]` lines filtered from console) |

---

## Notes

- `poop_fetcher` mode is gracefully migrated to `sports`. You're welcome.
- `[DEBUG]` prefixed log lines go to `ticker.log` only — console stays clean
- Backend runs on Ubuntu, controller on Pi — they're the same repo, deployed independently
