# sports_ticker/fetchers Agent Guide

Fetcher modules normalize external APIs into ticker game objects.

## Conventions
- Keep network calls behind short timeouts.
- Cache live data for a few seconds; cache static metadata/weather longer.
- Never let a failed API call crash the refresh loop. Return stale cache or a placeholder.
- Normalize display fields in the fetcher so renderers stay simple.

## Important Mixins
- `sports_indycar.py`: IndyCar race-control feed plus IMS weather.
- `sports_f1.py`: OpenF1 latest session data.
- `sports_modes.py`: orchestrates buffer refresh and snapshots (composes pins + buffers).
- `sports_modes_pins.py`: pinned-game fetch handlers (NHL native, ESPN, FotMob, etc.).
- `sports_modes_buffers.py`: per-mode `_build_*_buffer` implementations.
- `sports_modes_common.py`: shared dispatch registry and module-level fetcher hooks.

## F1 SignalR (optional live overlay)
- `f1_signalr.py` connects to livetiming.formula1.com when enabled.
- **Off by default** (server IPs are usually blocked).
- Enable locally: `set F1_SIGNALR=1` before starting the backend, or run with `SPORTS_TICKER_DEV=1` / `FLASK_DEBUG=1` (auto-on unless `F1_SIGNALR=0`).
