# Sports Ticker Backend

A comprehensive Flask-based backend server for managing sports scores, stock data, weather information, and Spotify integration for LED matrix display tickers.

## Overview

The Sports Ticker Backend is a powerful API server designed to aggregate and serve real-time sports scores, stock market data, weather updates, and music information to LED matrix display devices (particularly RGB LED panels via Raspberry Pi). It supports multiple sports leagues, stock tracking, custom team configurations, and goal horn playback integration.

## Features

### Sports Data
- **NHL** - National Hockey League
- **NBA** - National Basketball Association
- **NFL** - National Football League
- **MLB** - Major League Baseball
- **AHL** - American Hockey League
- **Soccer Leagues**:
  - Premier League (EPL)
  - FA Cup
  - Championship
  - League One & Two
  - FIFA World Cup
  - Champions League
  - Europa League
  - MLS
- **College Sports**:
  - NCAA Football (FBS & FCS)
- **Racing**:
  - Formula 1
  - NASCAR

### Additional Features
- **Live Sports News** - Breaking sports news from ESPN RSS feed
  - Automatically filtered for major events (trades, signings, injuries, etc.)
  - Interspersed between sports scores
  - Updates every 5 minutes
  - Free - no API key required
- Real-time stock price tracking with Finnhub API integration
- Weather data integration
- Clock display
- Spotify "Now Playing" integration
- Custom team favorites and filtering
- Multi-ticker device management
- Goal horn audio streaming to ESP32 devices
- Automated cache cleanup and data refresh

## Prerequisites

- Python 3.7+
- Flask
- Raspberry Pi with RGB LED Matrix (for ticker display)
- API Keys (optional but recommended):
  - Finnhub API keys for stock data
  - Spotify API credentials for music integration

## Installation

1. Clone the repository:
```bash
git clone https://github.com/MattLD13/SportsTickerBackend.git
cd SportsTickerBackend
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your API credentials:
```env
# Finnhub Stock API Keys
FINNHUB_KEY_1=your_key_here
FINNHUB_KEY_2=your_key_here
FINNHUB_KEY_3=your_key_here
FINNHUB_KEY_4=your_key_here
FINNHUB_KEY_5=your_key_here

# Spotify API Keys (Web API)
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REFRESH_TOKEN=your_refresh_token

# Spotify Credentials (Librespot)
SPOTIFY_USERNAME=your_spotify_username
SPOTIFY_PASSWORD=your_spotify_password
```

4. Run the server:
```bash
python app.py
```

The server will start on `http://0.0.0.0:5000` by default.

## Configuration

The backend automatically creates a `ticker_data` directory to store ticker-specific configurations and a `global_config.json` for server-wide settings.

### Global Configuration
- Sports update interval: 5 seconds
- Stock update interval: 30 seconds
- Worker thread count: 10
- API timeout: 3 seconds

## API Endpoints

### Configuration & Setup

#### `POST /api/config`
Update ticker configuration with league preferences and team favorites.

**Request Body:**
```json
{
  "ticker_id": "ticker_123",
  "active_sports": {
    "nhl": true,
    "nba": true,
    "mlb": false
  },
  "active_leagues": {
    "soccer_epl": true,
    "nfl": true
  },
  "favorite_teams": ["Team1", "Team2"]
}
```

#### `POST /pair`
Pair a new ticker device with the backend.

**Request Body:**
```json
{
  "ticker_id": "unique_ticker_id",
  "pair_code": "6-digit-code"
}
```

#### `POST /pair/id`
Generate a new pairing ID for device registration.

#### `POST /ticker/<tid>/unpair`
Unpair a ticker device from the backend.

### Data Retrieval

#### `GET /data?ticker_id=<tid>`
Retrieve all configured data for a specific ticker.

**Response:**
```json
{
  "leagues": [...],
  "sports": {
    "nhl": [...],
    "nba": [...]
  },
  "stocks": [...],
  "weather": {...},
  "music": {...}
}
```

#### `GET /leagues`
Get list of all available sports leagues and data types.

#### `GET /api/state`
Get current server state including all active tickers and their data.

#### `GET /api/teams`
Get list of all available teams across all sports.

#### `GET /api/my_teams?ticker_id=<tid>`
Get favorite teams for a specific ticker.

#### `GET /tickers`
Get list of all paired ticker devices.

### Spotify Integration

#### `GET /api/spotify/now`
Get currently playing Spotify track information.

**Response:**
```json
{
  "is_playing": true,
  "artist": "Artist Name",
  "title": "Song Title",
  "album": "Album Name"
}
```

### Hardware Control

#### `POST /api/hardware`
Send commands to ticker hardware devices (update, restart, etc.).

**Request Body:**
```json
{
  "action": "update",
  "ticker_id": "ticker_123"
}
```

### Debug & Monitoring

#### `POST /api/debug`
Enable debug logging for specific ticker.

#### `GET /errors`
Retrieve error logs from the server.

## Components

### Main Application (`app.py`)
The primary Flask server that:
- Manages API endpoints
- Handles ticker device pairing and configuration
- Fetches and caches sports data from multiple sources
- Aggregates stock market data using Finnhub API
- Manages Spotify integration
- Coordinates multi-threaded data updates

### Ticker Controller (`ticker_controller.py`)
The display controller for Raspberry Pi RGB LED matrices that:
- Renders game scores, stocks, and weather on LED panels
- Manages page transitions and animations
- Handles team logos and color schemes
- Provides WiFi setup interface for initial configuration
- Communicates with the backend server for data updates

### ESP Streamer (`ESPstreamer/`)
Audio streaming component for ESP32 devices:
- `streamer.py` - Flask server for managing goal horn audio
- `goalHorns.py` - Goal horn playback automation
- Converts and uploads MP3 files to ESP32 speakers
- Controls audio playback (play, stop, volume)

### iOS App (`iosApp.swift`)
SwiftUI-based mobile application for:
- Pairing and managing ticker devices
- Configuring sports leagues and team preferences
- Viewing live scores and standings
- Remote ticker control

## Deployment

The repository includes GitHub Actions workflows (`.github/workflows/deploy.yml`) for automated deployment:

1. Automatic deployment on push to `main` branch
2. SCP file transfer to production server
3. Environment variable configuration
4. Service restart via systemd

## Data Sources

- **Sports**: ESPN API, NHL API, FotMob (Soccer)
- **Stocks**: Finnhub API
- **Weather**: Custom weather API integration
- **Music**: Spotify Web API and Librespot

## Logging

Server logs are automatically written to `ticker.log` for debugging and monitoring purposes.

## Version

Current Server Version: `v0.6-Stable`

## License

This project is provided as-is for personal and educational use.

## Support

For issues, questions, or contributions, please open an issue on the GitHub repository.

## Architecture Notes

- **Multi-threaded Design**: Uses concurrent workers for parallel API requests
- **Connection Pooling**: HTTP adapter with connection pooling for optimal performance
- **Caching**: Implements intelligent caching for stocks and sports data
- **Rate Limiting**: Built-in rate limiting for external API calls
- **Error Handling**: Comprehensive error handling and logging throughout

## Development

### Running Tests
Currently, this project does not have automated tests. Manual testing is performed by:
1. Starting the Flask server
2. Testing API endpoints with curl or Postman
3. Verifying data display on connected ticker devices

### Code Structure
- API routes are defined in `app.py`
- Data fetching logic uses concurrent futures for parallel execution
- Configuration is stored per-ticker in JSON files
- LED matrix rendering is handled by `ticker_controller.py`
