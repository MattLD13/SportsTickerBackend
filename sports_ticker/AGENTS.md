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

## Score Alerts
- `services/score_alerts.py` diffs each new sports buffer against the previous one and turns score increases into described plays ("GRAND SLAM", "POWER PLAY GOAL").
- Detection is wired into `fetchers/sports_modes.py` at the point the sports buffer is published — the only place both the old and new score exist.
- Context comes from a `last_play` key on the game object. Fetchers populate it: ESPN via `normalize_last_play`, NHL via `nhl_last_goal`. A sport without it still gets a headline from the score delta alone.
- `/data` serves alerts under `alerts`, filtered to the ticker's followed teams and to `SPORTS_MODE_FAMILY` modes. A board set to weather/clock/music/flights/golf/racing is never interrupted. The league filter does not apply — a followed team alerts even with its league switched off.
- `GET /api/debug/score_alert?id=<ticker>` injects a synthetic alert through the same buffer and gating, for checking the takeover on real panels without waiting for a game. It reports `will_display` and `blocked_by` rather than failing silently.
- Alerts respect `live_delay_seconds`: `recent(delay=...)` holds each one back by the same amount as the content, so the takeover never announces a play before the delayed strip reaches it. Any new consumer of `recent()` must pass the delay too.

## Racing Payloads
- IndyCar payload key: `indycar`.
- F1 payload key: `f1`.
- Both use `type: racing`, `drivers`, `flag`, `session_type`, and optional `weather`.
