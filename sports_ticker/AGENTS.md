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
- `services/score_alerts.py` compares each new sports buffer with the previous one. It gives a name to each score increase, such as "GRAND SLAM" or "POWER PLAY GOAL".
- `fetchers/sports_modes.py` publishes the sports buffer. It runs the detector at that point, the only point where both the old score and the new score exist.
- Context comes from the `last_play` key on the game object. ESPN fetchers fill it with `normalize_last_play`. NHL fetchers use `nhl_last_goal`.
- A sport without `last_play` still gets a headline. The detector builds that headline from the score delta alone.
- `/data` returns alerts under the `alerts` key. It sends an alert only for a followed team, and only to a ticker in a `SPORTS_MODE_FAMILY` mode.
- The league filter does not apply to alerts. When its league is off, a followed team still shows an alert.
- Alerts obey `live_delay_seconds`. `recent(delay=...)` holds each alert for the same time as the content. A new caller of `recent()` must pass the delay.
- `GET /api/debug/score_alert?id=<ticker>` adds a synthetic alert to the same buffer. Use it to see the takeover on real panels without a live game.
- The debug route reports `will_display` and `blocked_by`. A ticker that stays dark tells you which gate stopped the alert.

## Racing Payloads
- IndyCar payload key: `indycar`.
- F1 payload key: `f1`.
- Both use `type: racing`, `drivers`, `flag`, `session_type`, and optional `weather`.
