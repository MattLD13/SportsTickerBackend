# Providers, projections, and records

## Ownership

| Boundary | Owner |
|---|---|
| Provider reads and source facts | `ticker/server/providers/` |
| Shared sports display facts | `ticker/shared/sports_display.py` |
| Per-ticker refresh and snapshots | `ticker/server/services/` |
| Pairing, device records, and durable events | `ticker/server/store/` |
| Public display data | `ticker/server/projections/data_api.py` |
| Compact Mini data | `ticker/server/projections/device_data.py`, `ticker/server/projections/mini_fields.py` |
| Encrypted Spotify connections and OAuth state | `ticker/server/spotify.py` |

## Sports and events

Normalize team identity before projecting display state.
Set `situation.activeTeam` in the provider projection.
Do not recover ownership from `Top`, `Bottom`, team names, URLs, or rendered text.
Scope stale provider data to the exact ticker settings that produced it.
Alerts and news are durable overlays. Targeted events remain isolated to their target ticker.
Use the provider contract, domain model, and projection as the explicit cross-device boundary.

## Validation

Run the focused provider and contract checks from the task packet.
After a display data change, run `python -m pytest -q`.
The routes, the engine, and the workers live in `ticker/server/`. Read `ticker/server/AGENTS.md` before you change them.
If a change affects Pi display output, render a real `384x32` frame before committing.
