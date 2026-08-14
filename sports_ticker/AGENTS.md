# sports_ticker Agent Guide

This package owns the V2 backend. Read the repository `AGENTS.md` in full before you change this package.

## Ownership

- `providers/` reads upstream sources and normalizes source facts.
- `providers/sports_display.py` owns sports display facts such as `activeTeam`.
- `application/` refreshes each ticker with that ticker's settings and persists snapshots.
- `fleet/` owns ticker records, pairing, controller sessions, and durable event storage.
- `projections/data_api.py` owns the public V2 data response.
- `api/routes.py` validates and exposes V2 routes.
- `integrations/spotify.py` owns encrypted Spotify connections and OAuth state.

## Rules

- Use only V2 routes and V2 data shapes.
- Keep one owner for each domain fact.
- Change the owner when a boundary is wrong. Do not duplicate parsing in a route, app, or renderer.
- Keep persistence, provider reads, projections, API validation, and renderer work separate.
- Delete obsolete callers, tests, fixtures, documentation, and imports when you replace a design.
- Add one focused test for a behavior. Use table cases in that test.
- Do not add a fallback for an obsolete payload. Reject it or migrate the producer.

## Sports display

- Normalize team identity before you project display state.
- Set `situation.activeTeam` in the provider projection.
- Do not make a client infer active ownership from `Top`, `Bottom`, names, URLs, or display text.
- Keep upstream stale data scoped to the exact ticker settings that produced it.

## Events

- Alerts and news are durable overlays.
- An overlay never changes or replaces base mode content.
- Targeted events remain isolated to their target ticker.

## Verification

Run `python -m pytest -q` after a V2 behavior change. If a change affects the Pi payload, render a 384x32 V2 frame with `tools/render_rewrite.py` before you commit.
