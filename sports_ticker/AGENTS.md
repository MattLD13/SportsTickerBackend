# sports_ticker Agent Guide

Backend package for configuration, data fetching, routes, and mode buffers.

## Key Files
- `core.py`: global state, constants, settings defaults, shared helpers.
- `leagues.py`: league/mode registry. Add new sport IDs here.
- `fetchers/sports.py`: composed sports fetcher class.
- `fetchers/sports_modes.py`: builds mode buffers and pinned-game refreshes.
- `routes/state.py`: `/data`, `/api/state`, pin filtering, per-ticker response shaping.
- `routes/preview.py`: backend PNG preview rendering.

## Fetcher Pattern
- Specialized fetchers live in `fetchers/sports_<name>.py`.
- Mix them into `SportsFetcher` in `fetchers/sports.py`.
- Use short TTL caches for fast live data and longer TTLs for static metadata/weather.
- Return normalized game objects with `type`, `sport`, `id`, `state`, `status`, `is_shown`, and mode-specific payload keys.

## Racing Payloads
- IndyCar payload key: `indycar`.
- F1 payload key: `f1`.
- Both use `type: racing`, `drivers`, `flag`, `session_type`, and optional `weather`.
