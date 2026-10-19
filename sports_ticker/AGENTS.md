# Ticker Server

## Ownership

| Boundary | Owner |
|---|---|
| Provider reads and source facts | `providers/` |
| Shared sports display facts | `providers/sports_display.py` |
| Per-ticker refresh and snapshots | `application/` |
| Pairing, device records, and durable events | `fleet/` |
| Public V2 data | `projections/data_api.py` |
| Compact Mini data | `projections/device_data.py`, `projections/mini_fields.py` |
| V2 validation and routes | `api/routes.py` |
| Encrypted Spotify connections and OAuth state | `integrations/spotify.py` |

## Sports and events

Normalize team identity before projecting display state.
Set `situation.activeTeam` in the provider projection.
Do not recover ownership from `Top`, `Bottom`, team names, URLs, or rendered text.
Scope stale provider data to the exact ticker settings that produced it.
Alerts and news are durable overlays. Targeted events remain isolated to their target ticker.
Use the provider contract, domain model, and projection as the explicit cross-device boundary.

## Validation

Run the focused provider and contract checks from the task packet.
After a V2 behavior change, run `python -m pytest -q`.
If a change affects Pi display output, render a real `384x32` frame before committing.
