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
- `sports_modes.py`: builds buffers for all active modes and pinned refreshes.
